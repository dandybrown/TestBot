import os
import sqlite3
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
from pytz import timezone
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Логи
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TZ = timezone("Europe/Amsterdam")
DB_PATH = "bot_db.sqlite"

# Инициализация БД
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY
        );
    """)
    conn.commit()
    conn.close()

def add_subscriber(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO subscribers(user_id) VALUES (?);", (user_id,))
    conn.commit()
    conn.close()

def get_all_subscribers():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM subscribers;")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_subscriber(user_id)
    await update.message.reply_text(
        "Вы подписались на ежедневное «Доброе утро!» в 08:00."
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return await update.message.reply_text("У вас нет прав администратора.")
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        return await update.message.reply_text("Использование: /broadcast <текст>")
    subscribers = get_all_subscribers()
    count = 0
    for uid in subscribers:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить {uid}: {e}")
    await update.message.reply_text(f"Рассылка отправлена {count} пользователям.")

# Функция ежедневного приветствия
def schedule_jobs(app: ApplicationBuilder):
    scheduler = BackgroundScheduler(timezone=TZ)
    # Каждый день в 08:00 Europe/Amsterdam
    trigger = CronTrigger(hour=8, minute=0, timezone=TZ)
    scheduler.add_job(
        func=lambda: app.bot.send_message(
            chat_id=uid, text="Доброе утро! ☀️"
        ) or None,
        trigger=trigger,
        args=[],
        id="daily_good_morning",
        replace_existing=True
    )
    # Чтобы отправлять всем подписчикам, обёрнём чуть иначе:
    def job_all():
        for uid in get_all_subscribers():
            try:
                app.bot.send_message(chat_id=uid, text="Доброе утро! ☀️")
            except Exception as e:
                logger.warning(f"Ошибка при рассылке {uid}: {e}")
    scheduler.reschedule_job("daily_good_morning", trigger=trigger, func=job_all)
    scheduler.start()
    logger.info("Планировщик запущен.")

# Точка входа
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Ждём, пока бот поднимется, и настраиваем задачи
    schedule_jobs(app)

    logger.info("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
