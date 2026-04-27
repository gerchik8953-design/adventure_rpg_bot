import os
import json
import logging
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8708829749:AAHSAHdxf6PO72JCSId9HfizI5qWEIpEZGI"
MISTRAL_API_KEY = "ouoo9FtDsaWEyAZTt3YZCaeqhQqvJSyc"

logging.basicConfig(level=logging.INFO)
USERS_FILE = "users.json"

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
    server.serve_forever()

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

def clean_callback_data(text: str) -> str:
    import hashlib
    return f"act_{hashlib.md5(text.encode('utf-8')).hexdigest()[:16]}"

def format_story_text(raw_text: str) -> str:
    text = raw_text.replace("ОПИСАНИЕ ПЕРСОНАЖА:", "🎭 **ОПИСАНИЕ ПЕРСОНАЖА:**")
    text = text.replace("НАЧАЛО ПРИКЛЮЧЕНИЯ:", "🌸 **НАЧАЛО ПРИКЛЮЧЕНИЯ:**")
    text = text.replace("Вариант", "🌀 **Вариант")
    return text

def ask_mistral(prompt, image_bytes):
    import base64
    url = "https://api.mistral.ai/v1/chat/completions"
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    payload = {
        "model": "pixtral-12b-2409",
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_base64}"}]}]
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {MISTRAL_API_KEY}"}
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        return "❌ Ошибка API"
    try:
        return response.json()["choices"][0]["message"]["content"]
    except:
        return "❌ Ошибка обработки"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    await update.message.reply_text("🎮 Отправь фото персонажа, начнём приключение!")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_user.id)
    await update.message.chat.send_action(action="typing")
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()
    prompt = "Опиши персонажа с юмором и начни историю с добрыми героями. Дай 3 варианта действий."
    response = ask_mistral(prompt, photo_bytes)
    keyboard = [[InlineKeyboardButton("➡️ Продолжить", callback_data="continue")]]
    await update.message.reply_text(response, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("История продолжается... (функция в разработке)")

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_action))
    print("✅ Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
