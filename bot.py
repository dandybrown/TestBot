import os
import sqlite3
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from pytz import timezone
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Логи
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
if not BOT_TOKEN or ADMIN_ID == 0:
    logger.error("Не заданы BOT_TOKEN или ADMIN_ID!")
    exit(1)

TZ = timezone("Europe/Amsterdam")
DB_PATH = "bot_db.sqlite"

# --- Инициализация БД ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Таблица подписчиков
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY
        );
    """)
    # Таблица напоминаний
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            remind_time TEXT NOT NULL,
            text TEXT NOT NULL
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

def add_reminder(user_id: int, remind_time: datetime, text: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reminders(user_id, remind_time, text) VALUES (?, ?, ?);",
        (user_id, remind_time.isoformat(), text),
    )
    reminder_id = cur.lastrowid
    conn.commit()
    conn.close()
    return reminder_id

def get_user_reminders(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, remind_time, text FROM reminders WHERE user_id = ? ORDER BY remind_time;",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_reminder(reminder_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM reminders WHERE id = ?;", (reminder_id,))
    conn.commit()
    conn.close()

# --- Планировщик напоминаний ---
scheduler = BackgroundScheduler(timezone=TZ)

def schedule_reminder(app, reminder_id, user_id, remind_time: datetime, text: str):
    def job():
        try:
            app.bot.send_message(chat_id=user_id, text=f"⏰ Напоминание: {text}")
        except Exception as e:
            logger.warning(f"Ошибка при отправке напоминания {reminder_id}: {e}")
        # после отработки — удаляем из БД
        delete_reminder(reminder_id)

    trigger = DateTrigger(run_date=remind_time, timezone=TZ)
    scheduler.add_job(job, trigger=trigger, id=f"reminder_{reminder_id}")

def load_and_schedule_all(app):
    for rid, rt_iso, text in sqlite3.connect(DB_PATH).cursor().execute(
        "SELECT id, remind_time, text, user_id FROM reminders"
    ):
        rt = datetime.fromisoformat(rt_iso)
        if rt > datetime.now(TZ):
            schedule_reminder(app, rid, user_id, rt, text)

# --- Обработчики команд и кнопок ---
# Главное меню
def main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton("➕ Создать напоминание", callback_data="menu_add")],
        [InlineKeyboardButton("📋 Мои напоминания", callback_data="menu_list")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="menu_about")],
    ]
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_subscriber(user_id)
    await update.message.reply_text(
        "Привет! Я бот-напоминалка.\nВы подписались на ежедневное «Доброе утро!» в 08:00.\n\n"
        "Выберите действие ниже:",
        reply_markup=main_menu_keyboard()
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Бот-напоминалка</b>\n\n"
        "• Отправляет ежедневное «Доброе утро!» в 08:00\n"
        "• Позволяет создавать напоминания на любую дату и время\n"
        "• Уведомляет вас лично, когда придёт время\n\n"
        "Команды:\n"
        "/start — меню бота\n"
        "/remind YYYY-MM-DD HH:MM текст — добавить напоминание\n"
        "/list — список ваших напоминаний\n"
        "/cancel ID — отменить напоминание\n"
    )
    # если из кнопки
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())

async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ожидаемый формат: /remind 2025-04-30 14:30 Позвонить врачу
    """
    user_id = update.effective_user.id
    try:
        date_str = context.args[0]
        time_str = context.args[1]
        text = " ".join(context.args[2:])
        remind_dt = TZ.localize(datetime.fromisoformat(f"{date_str}T{time_str}"))
        if remind_dt <= datetime.now(TZ):
            raise ValueError("Указано время в прошлом")
    except Exception:
        return await update.message.reply_text(
            "Неверный формат. Используйте:\n"
            "/remind YYYY-MM-DD HH:MM текст напоминания"
        )

    rid = add_reminder(user_id, remind_dt, text)
    schedule_reminder(context.application, rid, user_id, remind_dt, text)
    await update.message.reply_text(f"✅ Напоминание #{rid} установлено на {remind_dt.strftime('%Y-%m-%d %H:%M')}.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reminders = get_user_reminders(user_id)
    if not reminders:
        return await update.message.reply_text("У вас нет активных напоминаний.")
    lines = [f"{rid}. {datetime.fromisoformat(rt).strftime('%Y-%m-%d %H:%M')} — {txt}"
             for rid, rt, txt in reminders]
    await update.message.reply_text("Ваши напоминания:\n" + "\n".join(lines))

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rid = int(context.args[0])
        delete_reminder(rid)
        # удаляем задачу из планировщика, если есть
        job_id = f"reminder_{rid}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        await update.message.reply_text(f"❌ Напоминание #{rid} отменено.")
    except Exception:
        await update.message.reply_text("Использование: /cancel <ID_напоминания>")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "menu_add":
        await query.answer()
        await query.edit_message_text(
            "Чтобы создать напоминание, введите команду:\n"
            "/remind YYYY-MM-DD HH:MM текст",
            reply_markup=main_menu_keyboard()
        )
    elif data == "menu_list":
        await query.answer()
        # имитируем вызов /list
        await list_command(update, context)
    elif data == "menu_about":
        await about(update, context)

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    if message.text:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"Сообщение от пользователя {user_id}:\n\n{message.text}"
        )
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=f"Фото от пользователя {user_id}"
        )
    elif message.document:
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=message.document.file_id,
            caption=f"Файл от пользователя {user_id}"
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"Сообщение от пользователя {user_id}: [неизвестный тип сообщения]"
        )

# Планировщик ежедневного «Доброе утро!» и пользовательских напоминаний
def schedule_jobs(app):
    # ежедневный «Доброе утро!»
    from apscheduler.triggers.cron import CronTrigger
    def job_all():
        for uid in get_all_subscribers():
            try:
                app.bot.send_message(chat_id=uid, text="Доброе утро! ☀️")
            except Exception as e:
                logger.warning(f"Ошибка при рассылке {uid}: {e}")

    cron = CronTrigger(hour=8, minute=0, timezone=TZ)
    scheduler.add_job(job_all, trigger=cron, id="daily_good_morning")
    # загрузка пользовательских
    load_and_schedule_all(app)

    scheduler.start()
    logger.info("Планировщик запущен.")

# Точка входа
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Устанавливаем список команд бота в Telegram-клиенте
    app.bot.set_my_commands([
        BotCommand("start", "Запустить бота / открыть меню"),
        BotCommand("remind", "Добавить напоминание: /remind YYYY-MM-DD HH:MM текст"),
        BotCommand("list", "Показать список ваших напоминаний"),
        BotCommand("cancel", "Отменить напоминание по ID"),
        BotCommand("about", "Информация о боте"),
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, forward_to_admin))

    schedule_jobs(app)

    logger.info("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
