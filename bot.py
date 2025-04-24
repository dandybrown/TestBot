from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
import sqlite3
import os

# Базовая конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = "bot_db.sqlite"
scheduler = BackgroundScheduler()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            time DATETIME,
            text TEXT
        );
    """)
    conn.commit()
    conn.close()

def add_reminder_to_db(user_id: int, time: datetime, text: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO reminders (user_id, time, text) VALUES (?, ?, ?)", (user_id, time, text))
    conn.commit()
    conn.close()

def get_user_reminders(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, time, text FROM reminders WHERE user_id = ?", (user_id,))
    reminders = cur.fetchall()
    conn.close()
    return reminders

def delete_reminder(reminder_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

# Обработчики команд
async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /add_reminder <время (чч:мм)> <текст>")
        return

    try:
        time = datetime.strptime(args[0], "%H:%M").replace(
            year=datetime.now().year,
            month=datetime.now().month,
            day=datetime.now().day
        )
        if time < datetime.now():
            time += timedelta(days=1)  # Напоминание на следующий день, если время прошло.
        text = " ".join(args[1:])
        add_reminder_to_db(user_id, time, text)
        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=time),
            args=(user_id, text),
        )
        await update.message.reply_text(f"Напоминание добавлено на {time.strftime('%H:%M')}: {text}")
    except ValueError:
        await update.message.reply_text("Некорректное время. Используйте формат чч:мм.")

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reminders = get_user_reminders(user_id)
    if not reminders:
        await update.message.reply_text("У вас нет напоминаний.")
        return

    keyboard = [
        [
            InlineKeyboardButton(f"{time} — {text[:20]}...", callback_data=f"delete_{reminder_id}")
        ]
        for reminder_id, time, text in reminders
    ]
    await update.message.reply_text(
        "Ваши напоминания:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def delete_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reminder_id = int(query.data.split("_")[1])
    delete_reminder(reminder_id)
    await query.edit_message_text("Напоминание удалено.")

# Отправка напоминания
async def send_reminder(user_id: int, text: str):
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    await application.bot.send_message(chat_id=user_id, text=f"Напоминание: {text}")

# Точка входа
def main():
    init_db()
    scheduler.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add_reminder", add_reminder))
    app.add_handler(CommandHandler("list_reminders", list_reminders))
    app.add_handler(CallbackQueryHandler(delete_reminder_callback, pattern="delete_.*"))

    app.run_polling()

if __name__ == "__main__":
    main()
