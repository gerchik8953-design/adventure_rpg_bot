import logging
import requests
import base64
import re
import hashlib
import threading
import os
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# -------------------------------------------------------------------
# НАСТРОЙКА
# -------------------------------------------------------------------
TELEGRAM_TOKEN = "8708829749:AAHSAHdxf6PO72JCSId9HfizI5qWEIpEZGI"
MISTRAL_API_KEY = "ouoo9FtDsaWEyAZTt3YZCaeqhQqvJSyc"

logging.basicConfig(level=logging.INFO)

# -------------------------------------------------------------------
# СЧЁТЧИК ПОЛЬЗОВАТЕЛЕЙ
# -------------------------------------------------------------------
USERS_FILE = "users.json"

def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def add_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        save_users(users)

# -------------------------------------------------------------------
# HEALTH-СЕРВЕР ДЛЯ RENDER
# -------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
    server.serve_forever()

# -------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -------------------------------------------------------------------
def clean_callback_data(text: str) -> str:
    hash_obj = hashlib.md5(text.encode('utf-8'))
    return f"act_{hash_obj.hexdigest()[:16]}"

def parse_options_from_text(content: str):
    options = []
    for line in content.split('\n'):
        line = line.strip()
        if re.match(r'^[\-\•\*]\s*(.+?)(?::|$)', line) or re.match(r'^\d+\.\s*(.+?)(?::|$)', line):
            opt = re.sub(r'^[\-\•\*\d\.]+\s*', '', line)
            if ':' in opt:
                opt = opt.split(':', 1)[1].strip()
            if 2 < len(opt) < 50:
                options.append(opt)
        elif 'Вариант' in line and ':' in line:
            opt = line.split(':', 1)[1].strip()
            if 2 < len(opt) < 50 and opt not in options:
                options.append(opt)
        elif '🔹' in line and ':' in line:
            opt = line.split(':', 1)[1].strip()
            if 2 < len(opt) < 50 and opt not in options:
                options.append(opt)

    if len(options) < 2:
        options = ["Исследовать окрестности", "Поговорить с жителем", "Пойти в таверну"]
    return options[:3]

def format_story_text(raw_text: str) -> str:
    text = raw_text.replace("ОПИСАНИЕ ПЕРСОНАЖА:", "🎭 **ОПИСАНИЕ ПЕРСОНАЖА:**")
    text = text.replace("НАЧАЛО ПРИКЛЮЧЕНИЯ:", "🌸 **НАЧАЛО ПРИКЛЮЧЕНИЯ:**")
    text = text.replace("Вариант", "🌀 **Вариант")

    lines = text.split('\n')
    formatted = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            formatted.append('')
            continue
        if not any(stripped.startswith(x) for x in ('🎭', '🌸', '🌀', '---', '**Вариант', '1️⃣', '2️⃣', '3️⃣')):
            formatted.append(f"✨ {line}")
        else:
            formatted.append(line)

    result = []
    for line in formatted:
        result.append(line)
        if line.startswith(('🎭', '🌸')):
            result.append("---")
    return '\n'.join(result)

# -------------------------------------------------------------------
# ОСНОВНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С MISTRAL
# -------------------------------------------------------------------
def generate_adventure_from_photo(image_bytes):
    url = "https://api.mistral.ai/v1/chat/completions"
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

    prompt = (
        "Ты — мастер RPG-игр. Пользователь прислал фото своего персонажа.\n\n"
        "1. Опиши персонажа (3–4 предложения).\n"
        "2. Придумай завязку приключения (3–4 предложения).\n"
        "3. В конце предложи 3 коротких варианта действий (каждый 2–4 слова).\n\n"
        "Формат ответа (строго соблюдай заголовки):\n"
        "ОПИСАНИЕ ПЕРСОНАЖА:\n[текст]\n"
        "НАЧАЛО ПРИКЛЮЧЕНИЯ:\n[текст]\n"
        "Вариант 1: ...\nВариант 2: ...\nВариант 3: ..."
    )

    payload = {
        "model": "pixtral-12b-2409",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{image_base64}"
                    }
                ]
            }
        ],
        "max_tokens": 800
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        logging.error(f"Mistral API error on generate: {response.status_code}")
        return None, None

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
        options = parse_options_from_text(content)
        return content, options
    except (KeyError, IndexError):
        return None, None

def continue_story(previous_text: str, chosen_action: str):
    url = "https://api.mistral.ai/v1/chat/completions"

    prompt = f"""
Это история RPG.

ПРЕДЫДУЩЕЕ СОБЫТИЕ (не меняй):
{previous_text}

ИГРОК ВЫБРАЛ ДЕЙСТВИЕ: "{chosen_action}"

Напиши продолжение (3–5 предложений), которое логично вытекает из этого выбора.
В конце предложи 3 новых коротких варианта действий (каждый 2–4 слова).

ФОРМАТ ОТВЕТА:
[текст продолжения...]

Вариант 1: [действие]
Вариант 2: [действие]
Вариант 3: [действие]
    """

    payload = {
        "model": "mistral-large-latest",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 800
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        logging.error(f"Mistral API error on continue: {response.status_code}")
        return None, None

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
        options = parse_options_from_text(content)
        return content, options
    except (KeyError, IndexError):
        return None, None

# -------------------------------------------------------------------
# ОБРАБОТЧИКИ ТЕЛЕГРАМ
# -------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 *Добро пожаловать в RPG-приключение с AI-рассказчиком!*\n\n"
        "📸 Пришли мне фото своего персонажа:\n"
        "• рисунок\n"
        "• игрушку\n"
        "• Lego-фигурку\n\n"
        "✨ Я придумаю историю и предложу варианты действий!\n\n"
        "📊 Команда /stats — сколько людей играют со мной.",
        parse_mode='Markdown'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    count = len(users)
    await update.message.reply_text(
        f"📊 Этим ботом воспользовались **{count}** уникальных пользователей.",
        parse_mode='Markdown'
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)

    await update.message.chat.send_action(action="typing")

    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    story_text, options = generate_adventure_from_photo(photo_bytes)
    if story_text is None:
        await update.message.reply_text(
            "❌ Не удалось сгенерировать приключение.\n"
            "Попробуй другое фото или повтори позже."
        )
        return

    context.user_data['current_story'] = story_text

    if not options:
        await update.message.reply_text(story_text)
        return

    keyboard = []
    action_map = {}
    for opt in options:
        callback_key = clean_callback_data(opt)
        action_map[callback_key] = opt
        keyboard.append([InlineKeyboardButton(f"🔹 {opt[:35]}", callback_data=callback_key)])

    context.user_data['action_map'] = action_map
    reply_markup = InlineKeyboardMarkup(keyboard)

    formatted_text = format_story_text(story_text)
    await update.message.reply_text(formatted_text, reply_markup=reply_markup, parse_mode='Markdown')

# -------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОТПРАВКИ ДЛИННЫХ СООБЩЕНИЙ
# -------------------------------------------------------------------
async def send_long_message(chat_id, text, reply_markup=None, parse_mode=None):
    """Отправляет длинное сообщение, разбивая его на части по 4096 символов."""
    MAX_LEN = 4096
    for i in range(0, len(text), MAX_LEN):
        part = text[i:i+MAX_LEN]
        if i == 0:
            # Первая часть — с кнопками
            await bot.send_message(chat_id=chat_id, text=part, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            # Остальные части — без кнопок
            await bot.send_message(chat_id=chat_id, text=part, parse_mode=parse_mode)

# -------------------------------------------------------------------
async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    callback_key = query.data
    chosen_action = context.user_data.get('action_map', {}).get(callback_key, '')
    if not chosen_action:
        await query.edit_message_text("❌ Ошибка. Попробуй начать заново с /start")
        return

    previous_story = context.user_data.get('current_story', '')
    await query.message.chat.send_action(action="typing")

    new_story_part, options = continue_story(previous_story, chosen_action)
    if new_story_part is None:
        await query.edit_message_text("❌ Не удалось продолжить историю. Начни заново с /start")
        return

    full_story = previous_story + "\n\n" + new_story_part
    context.user_data['current_story'] = full_story

    if not options:
        await query.edit_message_text(full_story)
        return

    keyboard = []
    action_map = {}
    for opt in options:
        callback_key = clean_callback_data(opt)
        action_map[callback_key] = opt
        keyboard.append([InlineKeyboardButton(f"🔹 {opt[:35]}", callback_data=callback_key)])

    context.user_data['action_map'] = action_map
    reply_markup = InlineKeyboardMarkup(keyboard)

    formatted_full = format_story_text(full_story)

    # Отправляем длинное сообщение, разбивая на части
    global bot
    bot = context.bot
    await send_long_message(query.message.chat_id, formatted_full, reply_markup, 'Markdown')

# -------------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------------
def main():
    # Запускаем health-сервер в фоновом потоке
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Небольшая задержка для предотвращения конфликтов
    time.sleep(2)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_action))

    print("✅ Бот Adventure RPG запущен и готов к работе")
    app.run_polling()

if __name__ == "__main__":
    main()
