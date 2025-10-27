# bot.py
import asyncio
import logging
import os
import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from dotenv import load_dotenv

# ================= ENV & LOGGING =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("habitbot")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

# ================= SINGLE-INSTANCE LOCK =================
LOCK_FILE = "habitbot.pid"

def acquire_lock_or_exit():
    """Простой PID-лок: предотвращает второй запуск на той же машине."""
    if os.path.exists(LOCK_FILE):
        raise SystemExit(
            f"Похоже, бот уже запущен (есть {LOCK_FILE}). "
            f"Если это не так — удалите файл и запустите снова."
        )
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

# ================= AIROGRAM & SCHEDULER =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Локальная TZ — Алматы
KZ_TZ = ZoneInfo("Asia/Almaty")
scheduler = AsyncIOScheduler(timezone=KZ_TZ)

DB_PATH = "habits.db"

# ================= FSM STATES =================
class HabitStates(StatesGroup):
    waiting_for_habit_name = State()
    waiting_for_habit_delete = State()
    waiting_for_habit_mark = State()

# ================= KEYBOARDS =================
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои привычки"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="➕ Добавить привычку"), KeyboardButton(text="✅ Отметить выполнение")],
            [KeyboardButton(text="🗑 Удалить привычку"), KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )

def get_habits_keyboard(habits, action_type="mark"):
    """
    habits: [(id, name, color), ...]
    """
    keyboard = []
    for habit_id, name, color in habits:
        cb = f"{'mark' if action_type=='mark' else 'delete'}_{habit_id}"
        keyboard.append([InlineKeyboardButton(text=f"{color} {name}", callback_data=cb)])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    )

# ================= DB INIT =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                created_at DATE,
                color TEXT DEFAULT '🔵'
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                reminder_time TIME DEFAULT '20:00'
            )
        """)
        await db.commit()

# ================= CRUD =================
async def add_habit(user_id, name, color="🔵"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO habits (user_id, name, created_at, color) VALUES (?, ?, ?, ?)",
            (user_id, name, datetime.now(KZ_TZ).date(), color)
        )
        await db.commit()

async def get_habits(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name, color FROM habits WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        return await cur.fetchall()

async def delete_habit(habit_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM habits WHERE id=? AND user_id=?", (habit_id, user_id))
        await db.execute("DELETE FROM records WHERE habit_id=?", (habit_id,))
        await db.commit()

async def mark_done(habit_id, done=True):
    today = datetime.now(KZ_TZ).date()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM records WHERE habit_id=? AND date=?", (habit_id, today))
        existing = await cur.fetchone()
        if existing:
            await db.execute("UPDATE records SET done=? WHERE id=?", (done, existing[0]))
        else:
            await db.execute(
                "INSERT INTO records (habit_id, date, done) VALUES (?, ?, ?)",
                (habit_id, today, done)
            )
        await db.commit()

async def get_today_progress(user_id):
    today = datetime.now(KZ_TZ).date()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT h.id, h.name, h.color, r.done 
            FROM habits h 
            LEFT JOIN records r ON h.id = r.habit_id AND r.date = ? 
            WHERE h.user_id = ?
            ORDER BY h.created_at DESC
        """, (today, user_id))
        return await cur.fetchall()

async def get_stats(user_id, days=7):
    since = datetime.now(KZ_TZ).date() - timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT h.name, h.color, COUNT(r.id) AS total_done
            FROM habits h
            LEFT JOIN records r ON h.id = r.habit_id AND r.done=1 AND r.date>=?
            WHERE h.user_id = ?
            GROUP BY h.id
            ORDER BY total_done DESC
        """, (since, user_id))
        return await cur.fetchall()

async def get_streak(user_id, habit_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if habit_id:
            cur = await db.execute("""
                SELECT date FROM records 
                WHERE habit_id=? AND done=1 
                ORDER BY date DESC
            """, (habit_id,))
        else:
            cur = await db.execute("""
                SELECT r.date FROM records r
                JOIN habits h ON r.habit_id = h.id
                WHERE h.user_id=? AND r.done=1
                ORDER BY r.date DESC
            """, (user_id,))
        records = await cur.fetchall()

    if not records:
        return 0

    streak = 0
    current_date = datetime.now(KZ_TZ).date()
    for (date_value,) in records:
        record_date = (
            datetime.strptime(date_value, "%Y-%m-%d").date()
            if isinstance(date_value, str) else date_value
        )
        if record_date == (current_date - timedelta(days=streak)):
            streak += 1
        else:
            break
    return streak

# ================= HANDLERS =================
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    welcome_text = (
        "🎯 Добро пожаловать в трекер привычек!\n\n"
        "Здесь вы можете:\n"
        "• 📋 Следить за своими привычками\n"
        "• ✅ Отмечать ежедневные выполнения\n"
        "• 📊 Смотреть статистику и прогресс\n"
        "• 🔔 Получать напоминания\n\n"
        "Выберите действие в меню ниже:"
    )
    await message.answer(welcome_text, reply_markup=get_main_menu())

@dp.message(F.text == "ℹ️ Помощь")
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    help_text = (
        "📖 **Как пользоваться ботом:**\n\n"
        "**📋 Мои привычки** — посмотреть все привычки и сегодняшний прогресс\n"
        "**➕ Добавить привычку** — создать новую привычку для отслеживания\n"
        "**✅ Отметить выполнение** — отметить выполненные привычки за сегодня\n"
        "**🗑 Удалить привычку** — удалить привычку из списка\n"
        "**📊 Статистика** — посмотреть прогресс за последние 7 дней\n\n"
        "💡 **Совет:** начните с 3–5 привычек."
    )
    await message.answer(help_text, reply_markup=get_main_menu())

@dp.message(F.text == "📋 Мои привычки")
async def list_habits_cmd(message: types.Message):
    habits = await get_today_progress(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек. Добавьте первую привычку!", reply_markup=get_main_menu())
        return

    today = datetime.now(KZ_TZ).strftime("%d.%m.%Y")
    text = f"📊 **Ваш прогресс на {today}:**\n\n"

    completed = 0
    for habit_id, name, color, done in habits:
        status = "✅" if done else "⏳"
        text += f"{color} {name} — {status}\n"
        if done:
            completed += 1

    total = len(habits)
    percentage = (completed / total) * 100 if total > 0 else 0
    text += f"\n🎯 **Прогресс:** {completed}/{total} ({percentage:.1f}%)"

    streak = await get_streak(message.from_user.id)
    if streak > 0:
        text += f"\n🔥 **Текущая серия:** {streak} дн."

    await message.answer(text, reply_markup=get_main_menu())

@dp.message(F.text == "➕ Добавить привычку")
async def add_habit_cmd(message: types.Message, state: FSMContext):
    await message.answer(
        "Введите название новой привычки:\n\nПримеры:\n• Утренняя зарядка\n• Чтение 30 минут\n• Пить воду",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔙 Отмена")]],
            resize_keyboard=True
        )
    )
    await state.set_state(HabitStates.waiting_for_habit_name)

@dp.message(HabitStates.waiting_for_habit_name)
async def process_habit_name(message: types.Message, state: FSMContext):
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer("Добавление привычки отменено", reply_markup=get_main_menu())
        return

    habit_name = (message.text or "").strip()
    if not habit_name:
        await message.answer("Название пустое. Введите корректное название (1–50 символов).")
        return
    if len(habit_name) > 50:
        await message.answer("Название слишком длинное. Максимум 50 символов.")
        return

    await add_habit(message.from_user.id, habit_name)
    await state.clear()
    await message.answer(f"✅ Привычка «{habit_name}» добавлена!", reply_markup=get_main_menu())

@dp.message(F.text == "✅ Отметить выполнение")
async def mark_done_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек. Добавьте первую привычку!", reply_markup=get_main_menu())
        return
    await message.answer("Выберите привычку для отметки:", reply_markup=get_habits_keyboard(habits, "mark"))

@dp.message(F.text == "🗑 Удалить привычку")
async def delete_habit_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек для удаления.", reply_markup=get_main_menu())
        return
    await message.answer("Выберите привычку для удаления:", reply_markup=get_habits_keyboard(habits, "delete"))

@dp.message(F.text == "📊 Статистика")
async def stats_cmd(message: types.Message):
    stats = await get_stats(message.from_user.id, 7)
    if not stats:
        await message.answer("Пока нет данных для статистики. Начните отмечать привычки!", reply_markup=get_main_menu())
        return

    text = "📈 **Статистика за 7 дней:**\n\n"
    total_done = 0
    for name, color, done_count in stats:
        text += f"{color} {name}: {done_count} раз\n"
        total_done += done_count

    streak = await get_streak(message.from_user.id)
    text += f"\n🔥 **Текущая серия:** {streak} дн."
    text += f"\n🎯 **Всего выполнено:** {total_done} раз"

    await message.answer(text, reply_markup=get_main_menu())

# ================= CALLBACKS =================
@dp.callback_query(F.data.startswith("mark_"))
async def mark_habit_callback(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    await mark_done(habit_id, True)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM habits WHERE id=?", (habit_id,))
        row = await cur.fetchone()
    habit_name = row[0] if row else "Привычка"
    await callback.message.edit_text(f"✅ Привычка «{habit_name}» отмечена как выполненная!")
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_"))
async def delete_habit_callback(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM habits WHERE id=?", (habit_id,))
        row = await cur.fetchone()
    habit_name = row[0] if row else "Привычка"
    await delete_habit(habit_id, callback.from_user.id)
    await callback.message.edit_text(f"🗑 Привычка «{habit_name}» удалена!")
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=get_main_menu())

# ================= REMINDERS =================
async def send_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT DISTINCT user_id FROM habits")
        users = await cur.fetchall()

    for (user_id,) in users:
        try:
            today_progress = await get_today_progress(user_id)
            unmarked = [habit for habit in today_progress if not habit[3]]
            if unmarked:
                reminder_text = "🔔 **Напоминание!**\n\nНе забудьте отметить привычки за сегодня:\n"
                for habit in unmarked[:5]:
                    reminder_text += f"• {habit[2]} {habit[1]}\n"  # color + name
                if len(unmarked) > 5:
                    reminder_text += f"• ... и ещё {len(unmarked) - 5} привычек\n"
                reminder_text += "\nИспользуйте кнопку «✅ Отметить выполнение»"
                await bot.send_message(user_id, reminder_text, reply_markup=get_main_menu())
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")

def setup_scheduler():
    # Стабильные ID + replace_existing — чтобы не плодить дубликаты
    scheduler.add_job(
        send_reminders,
        CronTrigger(hour=20, minute=0),
        id="reminder_20_00",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300
    )
    scheduler.add_job(
        send_reminders,
        CronTrigger(hour=9, minute=0),
        id="reminder_09_00",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300
    )
    scheduler.start()

# ================= SHUTDOWN =================
async def on_shutdown():
    # Аккуратно гасим планировщик и сессию бота
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        await bot.session.close()
    except Exception:
        pass
    release_lock()
    logger.info("Бот корректно остановлен.")
# === DB MIGRATION (добавляет недостающие колонки без потери данных) ===
async def migrate_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Узнаём список колонок в habits
        cur = await db.execute("PRAGMA table_info(habits)")
        cols = [row[1] for row in await cur.fetchall()]  # row[1] = name

        # color
        if "color" not in cols:
            await db.execute("ALTER TABLE habits ADD COLUMN color TEXT DEFAULT '🔵'")
            # на всякий случай проставим значение тем, у кого NULL
            await db.execute("UPDATE habits SET color='🔵' WHERE color IS NULL")

        # created_at (если вдруг старая схема без этой колонки)
        if "created_at" not in cols:
            await db.execute("ALTER TABLE habits ADD COLUMN created_at DATE")
            # заполним текущей датой, чтобы сортировка не падала
            from datetime import datetime
            from zoneinfo import ZoneInfo
            KZ_TZ = ZoneInfo("Asia/Almaty")
            today = datetime.now(KZ_TZ).date().isoformat()
            await db.execute("UPDATE habits SET created_at=?", (today,))

        await db.commit()
    

# ================= MAIN =================
async def main():
    acquire_lock_or_exit()
    await init_db()

    await migrate_db()  # <-- добавьте эту строку

    

    # Важно: снимаем webhook и чистим очереди, иначе возможны конфликты с polling
    await bot.delete_webhook(drop_pending_updates=True)

    setup_scheduler()
    logger.info("Бот запущен!")

    # aiogram v3: корректный способ ограничить типы апдейтов
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Даже при исключении корректно освобождаем ресурсы (исчезнут unclosed session / SSL ошибки)
        await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit as e:
        logger.error(str(e))
    except KeyboardInterrupt:
        pass
    finally:
        release_lock()
