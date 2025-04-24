import os
import sqlite3
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Логи
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "reminders_db.sqlite"

# Инициализация БД
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            user_id INTEGER,
            reminder TEXT,
            time TEXT,
            PRIMARY KEY (user_id, reminder, time)
        );
    """)
    conn.commit()
    conn.close()

def add_reminder(user_id: int, reminder: str, time: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO reminders (user_id, reminder, time) VALUES (?, ?, ?);", (user_id, reminder, time))
    conn.commit()
    conn.close()

def get_reminders(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT reminder, time FROM reminders WHERE user_id = ?;", (user_id,))
    reminders = cur.fetchall()
    conn.close()
    return reminders

def delete_reminder(user_id: int, reminder: str, time: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM reminders WHERE user_id = ? AND reminder = ? AND time = ?;", (user_id, reminder, time))
    conn.commit()
    conn.close()

# Обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Вы можете добавлять напоминания с помощью команды /remind "
        "и управлять ими через меню /menu."
    )

async def add_reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        time_str = context.args[0]
        reminder = " ".join(context.args[1:])
        reminder_time = datetime.strptime(time_str, "%H:%M")
        now = datetime.now()
        if reminder_time < now.time():
            reminder_time += timedelta(days=1)  # Напоминание на следующий день

        add_reminder(user_id, reminder, time_str)
        await context.job_queue.run_once(
            send_reminder, 
            when=(reminder_time - now).seconds, 
            context={"user_id": user_id, "reminder": reminder}
        )
        await update.message.reply_text(f"Напоминание установлено: {reminder} в {time_str}.")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /remind <HH:MM> <текст напоминания>")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.context
    user_id = job_data["user_id"]
    reminder = job_data["reminder"]
    await context.bot.send_message(chat_id=user_id, text=f"Напоминание: {reminder}")

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reminders = get_reminders(user_id)
    if not reminders:
        return await update.message.reply_text("У вас нет установленных напоминаний.")

    keyboard = [
        [InlineKeyboardButton(f"{time} - {reminder}", callback_data=f"delete_{time}_{reminder}")]
        for reminder, time in reminders
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Ваши напоминания:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data.startswith("delete_"):
        _, time, reminder = query.data.split("_", 2)
        delete_reminder(user_id, reminder, time)
        await query.edit_message_text(f"Напоминание удалено: {reminder} в {time}.")

# Точка входа
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("remind", add_reminder_command))
    app.add_handler(CommandHandler("menu", show_menu))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
