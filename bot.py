import asyncio
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import asyncio
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

DB_PATH = "habits.db"


# === ИНИЦИАЛИЗАЦИЯ БД ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                created_at DATE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER,
                date DATE,
                done BOOLEAN,
                FOREIGN KEY (habit_id) REFERENCES habits(id)
            )
        """)
        await db.commit()


# === CRUD ОПЕРАЦИИ ===
async def add_habit(user_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO habits (user_id, name, created_at) VALUES (?, ?, ?)",
                         (user_id, name, datetime.now().date()))
        await db.commit()

async def get_habits(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, name FROM habits WHERE user_id = ?", (user_id,))
        return await cursor.fetchall()

async def delete_habit(habit_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM habits WHERE id=? AND user_id=?", (habit_id, user_id))
        await db.commit()

async def mark_done(habit_id, done=True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO records (habit_id, date, done) VALUES (?, ?, ?)",
                         (habit_id, datetime.now().date(), done))
        await db.commit()

async def get_stats(user_id, days=7):
    async with aiosqlite.connect(DB_PATH) as db:
        since = datetime.now().date() - timedelta(days=days)
        cursor = await db.execute("""
            SELECT h.name, COUNT(r.id) AS total_done
            FROM habits h
            LEFT JOIN records r ON h.id = r.habit_id AND r.done=1 AND r.date>=?
            WHERE h.user_id = ?
            GROUP BY h.id
        """, (since, user_id))
        return await cursor.fetchall()


# === ОБРАБОТЧИКИ КОМАНД ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer("👋 Привет! Я бот для трекинга привычек.\n"
                         "Команды:\n"
                         "/add — добавить привычку\n"
                         "/list — показать все привычки\n"
                         "/delete — удалить привычку\n"
                         "/done — отметить выполненное\n"
                         "/stats — статистика\n")

@dp.message(Command("add"))
async def add_cmd(message: types.Message):
    await message.answer("Введите название привычки:")

    @dp.message()
    async def get_name(msg: types.Message):
        await add_habit(msg.from_user.id, msg.text)
        await msg.answer(f"✅ Привычка '{msg.text}' добавлена!")
        dp.message.unregister(get_name)

@dp.message(Command("list"))
async def list_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек.")
        return
    text = "\n".join([f"{hid}. {name}" for hid, name in habits])
    await message.answer(f"📋 Ваши привычки:\n{text}")

@dp.message(Command("delete"))
async def delete_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("Нет привычек для удаления.")
        return
    text = "\n".join([f"{hid}. {name}" for hid, name in habits])
    await message.answer(f"Введите ID привычки для удаления:\n{text}")

    @dp.message()
    async def get_id(msg: types.Message):
        try:
            await delete_habit(int(msg.text), msg.from_user.id)
            await msg.answer("🗑 Привычка удалена!")
        except:
            await msg.answer("❌ Ошибка: неверный ID.")
        dp.message.unregister(get_id)

@dp.message(Command("done"))
async def done_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("Нет привычек для отметки.")
        return
    text = "\n".join([f"{hid}. {name}" for hid, name in habits])
    await message.answer(f"Введите ID привычки, которую выполнили:\n{text}")

    @dp.message()
    async def mark(msg: types.Message):
        try:
            await mark_done(int(msg.text))
            await msg.answer("🎯 Отлично! Отмечено как выполнено.")
        except:
            await msg.answer("❌ Ошибка: неверный ID.")
        dp.message.unregister(mark)

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    stats = await get_stats(message.from_user.id, 7)
    if not stats:
        await message.answer("Нет данных для статистики.")
        return
    text = "\n".join([f"{name}: {done} раз(а)" for name, done in stats])
    await message.answer(f"📊 Статистика за 7 дней:\n{text}")


# === НАПОМИНАНИЯ ===
async def send_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT user_id FROM habits")
        users = await cursor.fetchall()
    for (user_id,) in users:
        await bot.send_message(user_id, "🔔 Напоминание: отметьте свои привычки за сегодня!")

def setup_scheduler():
    scheduler.add_job(send_reminders, CronTrigger(hour=20, minute=0))  # ежедневно в 20:00
    scheduler.start()


# === MAIN ===
async def main():
    await init_db()
    setup_scheduler()
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())