import os
import json
import logging
import requests
import threading
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
# ПРОСТЕЙШИЙ ОБРАБОТЧИК
# -------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот работает! Отправь фото.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Фото получено, но генерация пока отключена для теста.")

# -------------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------------
def main():
    # Health-сервер в фоне
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("✅ Бот запущен (тестовая версия)")
    app.run_polling()

if __name__ == "__main__":
    main()
🐳 Шаг 3. Проверьте файл Dockerfile
Откройте его на GitHub. Должно быть точно так (без лишних пробелов и пустых строк в конце):

dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "adventure_bot.py"]
