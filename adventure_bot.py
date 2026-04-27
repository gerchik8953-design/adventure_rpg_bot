import os
import json
import logging
import requests
import threading
import hashlib
import time
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8708829749:AAHSAHdxf6PO72JCSId9HfizI5qWEIpEZGI"
MISTRAL_API_KEY = "ouoo9FtDsaWEyAZTt3YZCaeqhQqvJSyc"

logging.basicConfig(level=logging.INFO)
USERS_FILE = "users.json"

# -------------------------------------------------------------------
# HEALTH-СЕРВЕР
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
# СЧЁТЧИК ПОЛЬЗОВАТЕЛЕЙ
# -------------------------------------------------------------------
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
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# -------------------------------------------------------------------
def clean_callback_data(text: str) -> str:
    return f"act_{hashlib.md5(text.encode('utf-8')).hexdigest()[:16]}"

def parse_options_from_text(content: str):
    """Извлекает варианты действий из ответа Mistral в разных форматах."""
    options = []
    
    # Формат 1: "Вариант 1: действие" или "1: действие"
    pattern1 = r'(?:Вариант\s*)?(\d+)[:\.\)]\s*\*?\*?([^*\n]+)'
    matches = re.findall(pattern1, content)
    for match in matches[:3]:
        opt = match[1].strip().strip('*')
        if opt and opt not in options:
            options.append(opt)
    
    # Формат 2: "1. **Действие**" (с жирным форматированием)
    if len(options) < 2:
        pattern2 = r'(\d+)\.\s+\*\*([^*]+)\*\*'
        matches = re.findall(pattern2, content)
        for match in matches[:3]:
            opt = match[1].strip()
            if opt and opt not in options:
                options.append(opt)
    
    # Формат 3: строки после "ВОТ ЧТО ТЫ МОЖЕШЬ СДЕЛАТЬ:" с цифрами
    if len(options) < 2:
        # Ищем блок после ключевой фразы
        block_match = re.search(r'ВОТ ЧТО ТЫ МОЖЕШЬ СДЕЛАТЬ:(.+?)(?=\n\n|\n[A-ZА-Я]|$)', content, re.DOTALL)
        if block_match:
            block = block_match.group(1)
            lines = block.split('\n')
            for line in lines:
                line = line.strip()
                # Ищем строки, начинающиеся с цифры
                if re.match(r'^\d+', line):
                    # Убираем номер и точку/скобку
                    opt = re.sub(r'^\d+[\.:\)]\s*', '', line)
                    opt = opt.strip('*').strip()
                    if opt and len(opt) > 5 and len(opt) < 60 and opt not in options:
                        options.append(opt)
    
    # Очищаем варианты от лишних символов
    cleaned = []
    for opt in options:
        opt = re.sub(r'\*', '', opt)
        opt = re.sub(r'[\[\]\(\)]', '', opt)
        opt = opt.strip()
        if opt and opt not in cleaned:
            cleaned.append(opt)
    
    if len(cleaned) < 2:
        cleaned = ["Исследовать окрестности", "Поговорить с жителем", "Пойти в таверну"]
    
    return cleaned[:3]

def format_story_text(raw_text: str) -> str:
    text = raw_text.replace("ОПИСАНИЕ ПЕРСОНАЖА:", "🎭 **ОПИСАНИЕ ПЕРСОНАЖА:**")
    text = text.replace("НАЧАЛО ПРИКЛЮЧЕНИЯ:", "🌸 **НАЧАЛО ПРИКЛЮЧЕНИЯ:**")
    text = text.replace("Вариант", "🌀 Вариант")
    return text

def split_long_message(text, max_len=4000):
    if len(text) <= max_len:
        return [text]
    parts = []
    while len(text) > max_len:
        split_point = text.rfind('\n\n', 0, max_len)
        if split_point == -1:
            split_point = text.rfind('\n', 0, max_len)
        if split_point == -1:
            split_point = max_len
        parts.append(text[:split_point])
        text = text[split_point:]
    parts.append(text)
    return parts

# -------------------------------------------------------------------
# ФУНКЦИИ ДЛЯ РАБОТЫ С MISTRAL
# -------------------------------------------------------------------
def ask_mistral(prompt, image_bytes=None):
    url = "https://api.mistral.ai/v1/chat/completions"
    
    if image_bytes:
        import base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_base64}"}]}]
    else:
        messages = [{"role": "user", "content": prompt}]
    
    payload = {"model": "pixtral-12b-2409" if image_bytes else "mistral-large-latest", "messages": messages, "max_tokens": 800}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {MISTRAL_API_KEY}"}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logging.error(f"Mistral API error: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Mistral exception: {e}")
        return None

def generate_adventure_from_photo(image_bytes):
    prompt = """Ты мастер RPG. Опиши персонажа с юмором (3-4 предложения). Придумай начало приключения с добрыми персонажами (3-4 предложения). В конце напиши "ВОТ ЧТО ТЫ МОЖЕШЬ СДЕЛАТЬ:" и затем 3 варианта действий, каждый с новой строки в формате "1. Действие".

Пример формата:
ОПИСАНИЕ ПЕРСОНАЖА: ...
НАЧАЛО ПРИКЛЮЧЕНИЯ: ...
ВОТ ЧТО ТЫ МОЖЕШЬ СДЕЛАТЬ:
1. Первое действие
2. Второе действие
3. Третье действие"""
    result = ask_mistral(prompt, image_bytes)
    if not result:
        return None, None
    options = parse_options_from_text(result)
    return result, options

def continue_story(previous_story, chosen_action):
    if len(previous_story) > 3000:
        previous_story = "...[предыдущая история сокращена]...\n" + previous_story[-3000:]
    
    prompt = f"""Это история RPG.

ПРЕДЫДУЩАЯ ИСТОРИЯ:
{previous_story}

ИГРОК ВЫБРАЛ: "{chosen_action}"

Напиши продолжение (3-5 предложений). В конце напиши "ВОТ ЧТО ТЫ МОЖЕШЬ СДЕЛАТЬ:" и затем 3 новых варианта действий, каждый с новой строки в формате "1. Действие".

Продолжение:"""
    
    result = ask_mistral(prompt)
    if not result:
        return None, None
    options = parse_options_from_text(result)
    return result, options

# -------------------------------------------------------------------
# ОБРАБОТЧИКИ ТЕЛЕГРАМ
# -------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    await update.message.reply_text(
        "🎮 Добро пожаловать в RPG-приключение!\n"
        "📸 Пришли фото своего персонажа.\n"
        "✨ Я начну историю и предложу варианты действий!"
    )

async def send_long_text(chat_id, text, reply_markup=None):
    parts = split_long_message(text)
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            await bot.send_message(chat_id=chat_id, text=part, reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text=part)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot
    bot = context.bot
    
    add_user(update.effective_user.id)
    await update.message.chat.send_action(action="typing")
    
    try:
        photo_file = await update.message.photo[-1].get_file(read_timeout=60)
        photo_bytes = await photo_file.download_as_bytearray()
    except Exception as e:
        logging.error(f"Photo download error: {e}")
        await update.message.reply_text("❌ Не удалось загрузить фото. Попробуй ещё раз.")
        return
    
    story, options = generate_adventure_from_photo(photo_bytes)
    if not story:
        await update.message.reply_text("❌ Ошибка генерации. Попробуй другое фото.")
        return
    
    context.user_data['current_story'] = story
    
    if options:
        action_map = {}
        keyboard = []
        for opt in options:
            key = clean_callback_data(opt)
            action_map[key] = opt
            keyboard.append([InlineKeyboardButton(f"🔹 {opt[:35]}", callback_data=key)])
        context.user_data['action_map'] = action_map
        formatted = format_story_text(story)
        await send_long_text(update.message.chat_id, formatted, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        formatted = format_story_text(story)
        await send_long_text(update.message.chat_id, formatted)

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot
    bot = context.bot
    
    query = update.callback_query
    await query.answer()
    
    callback_key = query.data
    chosen_action = context.user_data.get('action_map', {}).get(callback_key, '')
    if not chosen_action:
        await query.edit_message_text("❌ Ошибка. Начни заново с /start")
        return
    
    previous_story = context.user_data.get('current_story', '')
    await query.message.chat.send_action(action="typing")
    
    new_part, options = continue_story(previous_story, chosen_action)
    if not new_part:
        await query.edit_message_text("❌ Ошибка генерации продолжения. Попробуй начать заново.")
        return
    
    full_story = previous_story + "\n\n" + new_part
    context.user_data['current_story'] = full_story
    
    if options:
        action_map = {}
        keyboard = []
        for opt in options:
            key = clean_callback_data(opt)
            action_map[key] = opt
            keyboard.append([InlineKeyboardButton(f"🔹 {opt[:35]}", callback_data=key)])
        context.user_data['action_map'] = action_map
        formatted = format_story_text(full_story)
        
        try:
            await query.message.delete()
        except:
            pass
        await send_long_text(query.message.chat_id, formatted, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        formatted = format_story_text(full_story)
        try:
            await query.message.delete()
        except:
            pass
        await send_long_text(query.message.chat_id, formatted)

# -------------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------------
def main():
    global bot
    threading.Thread(target=run_health_server, daemon=True).start()
    time.sleep(1)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_action))
    
    bot = app.bot
    
    print("✅ Бот Adventure RPG запущен и готов к работе")
    app.run_polling()

if __name__ == "__main__":
    main()
