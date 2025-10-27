import asyncio
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
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

# === СОСТОЯНИЯ ===
class HabitStates(StatesGroup):
    waiting_for_habit_name = State()
    waiting_for_habit_delete = State()
    waiting_for_habit_mark = State()

# === КЛАВИАТУРЫ ===
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
    keyboard = []
    for habit_id, name in habits:
        if action_type == "mark":
            callback_data = f"mark_{habit_id}"
        else:
            callback_data = f"delete_{habit_id}"
        
        keyboard.append([InlineKeyboardButton(text=name, callback_data=callback_data)])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    )

# === ИНИЦИАЛИЗАЦИЯ БД ===
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

# === CRUD ОПЕРАЦИИ ===
async def add_habit(user_id, name, color="🔵"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO habits (user_id, name, created_at, color) VALUES (?, ?, ?, ?)",
                         (user_id, name, datetime.now().date(), color))
        await db.commit()

async def get_habits(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, name, color FROM habits WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return await cursor.fetchall()

async def delete_habit(habit_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM habits WHERE id=? AND user_id=?", (habit_id, user_id))
        await db.execute("DELETE FROM records WHERE habit_id=?", (habit_id,))
        await db.commit()

async def mark_done(habit_id, done=True):
    today = datetime.now().date()
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, есть ли уже запись на сегодня
        cursor = await db.execute("SELECT id FROM records WHERE habit_id=? AND date=?", (habit_id, today))
        existing = await cursor.fetchone()
        
        if existing:
            await db.execute("UPDATE records SET done=? WHERE id=?", (done, existing[0]))
        else:
            await db.execute("INSERT INTO records (habit_id, date, done) VALUES (?, ?, ?)",
                             (habit_id, today, done))
        await db.commit()

async def get_today_progress(user_id):
    today = datetime.now().date()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT h.id, h.name, h.color, r.done 
            FROM habits h 
            LEFT JOIN records r ON h.id = r.habit_id AND r.date = ? 
            WHERE h.user_id = ?
            ORDER BY h.created_at DESC
        """, (today, user_id))
        return await cursor.fetchall()

async def get_stats(user_id, days=7):
    async with aiosqlite.connect(DB_PATH) as db:
        since = datetime.now().date() - timedelta(days=days)
        cursor = await db.execute("""
            SELECT h.name, h.color, COUNT(r.id) AS total_done
            FROM habits h
            LEFT JOIN records r ON h.id = r.habit_id AND r.done=1 AND r.date>=?
            WHERE h.user_id = ?
            GROUP BY h.id
            ORDER BY total_done DESC
        """, (since, user_id))
        return await cursor.fetchall()

async def get_streak(user_id, habit_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if habit_id:
            cursor = await db.execute("""
                SELECT date FROM records 
                WHERE habit_id=? AND done=1 
                ORDER BY date DESC
            """, (habit_id,))
        else:
            cursor = await db.execute("""
                SELECT r.date FROM records r
                JOIN habits h ON r.habit_id = h.id
                WHERE h.user_id=? AND r.done=1
                ORDER BY r.date DESC
            """, (user_id,))
        
        records = await cursor.fetchall()
        if not records:
            return 0
        
        streak = 0
        current_date = datetime.now().date()
        
        for record in records:
            record_date = datetime.strptime(record[0], '%Y-%m-%d').date() if isinstance(record[0], str) else record[0]
            
            if record_date == current_date - timedelta(days=streak):
                streak += 1
            else:
                break
                
        return streak

# === ОБРАБОТЧИКИ КОМАНД ===
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    welcome_text = """
🎯 Добро пожаловать в трекер привычек!

Здесь вы можете:
• 📋 Следить за своими привычками
• ✅ Отмечать ежедневные выполнения
• 📊 Смотреть статистику и прогресс
• 🔔 Получать напоминания

Выберите действие в меню ниже:
    """
    await message.answer(welcome_text, reply_markup=get_main_menu())

@dp.message(F.text == "ℹ️ Помощь")
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    help_text = """
📖 **Как пользоваться ботом:**

**📋 Мои привычки** - посмотреть все привычки и сегодняшний прогресс
**➕ Добавить привычку** - создать новую привычку для отслеживания
**✅ Отметить выполнение** - отметить выполненные привычки за сегодня
**🗑 Удалить привычку** - удалить привычку из списка
**📊 Статистика** - посмотреть прогресс за последние 7 дней

💡 **Совет:** Старайтесь добавлять не более 3-5 привычек сначала, чтобы не перегружать себя!
    """
    await message.answer(help_text, reply_markup=get_main_menu())

@dp.message(F.text == "📋 Мои привычки")
async def list_habits_cmd(message: types.Message):
    habits = await get_today_progress(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек. Добавьте первую привычку!", reply_markup=get_main_menu())
        return
    
    today = datetime.now().strftime("%d.%m.%Y")
    text = f"📊 **Ваш прогресс на {today}:**\n\n"
    
    completed = 0
    for habit_id, name, color, done in habits:
        status = "✅" if done else "⏳"
        text += f"{color} {name} - {status}\n"
        if done:
            completed += 1
    
    total = len(habits)
    percentage = (completed / total) * 100 if total > 0 else 0
    
    text += f"\n🎯 **Прогресс:** {completed}/{total} ({percentage:.1f}%)"
    
    # Добавляем информацию о серии
    streak = await get_streak(message.from_user.id)
    if streak > 0:
        text += f"\n🔥 **Текущая серия:** {streak} дней"
    
    await message.answer(text, reply_markup=get_main_menu())

@dp.message(F.text == "➕ Добавить привычку")
async def add_habit_cmd(message: types.Message, state: FSMContext):
    await message.answer("Введите название новой привычки:\n\nПримеры:\n• Утренняя зарядка\n• Чтение 30 минут\n• Пить воду", 
                        reply_markup=ReplyKeyboardMarkup(
                            keyboard=[[KeyboardButton(text="🔙 Отмена")]],
                            resize_keyboard=True
                        ))
    await state.set_state(HabitStates.waiting_for_habit_name)

@dp.message(HabitStates.waiting_for_habit_name)
async def process_habit_name(message: types.Message, state: FSMContext):
    if message.text == "🔙 Отмена":
        await state.clear()
        await message.answer("Добавление привычки отменено", reply_markup=get_main_menu())
        return
    
    habit_name = message.text.strip()
    if len(habit_name) > 50:
        await message.answer("Название привычки слишком длинное. Максимум 50 символов.")
        return
    
    await add_habit(message.from_user.id, habit_name)
    await state.clear()
    await message.answer(f"✅ Привычка '{habit_name}' успешно добавлена!", reply_markup=get_main_menu())

@dp.message(F.text == "✅ Отметить выполнение")
async def mark_done_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек. Добавьте первую привычку!", reply_markup=get_main_menu())
        return
    
    await message.answer("Выберите привычку для отметки:", 
                        reply_markup=get_habits_keyboard(habits, "mark"))

@dp.message(F.text == "🗑 Удалить привычку")
async def delete_habit_cmd(message: types.Message):
    habits = await get_habits(message.from_user.id)
    if not habits:
        await message.answer("У вас пока нет привычек для удаления.", reply_markup=get_main_menu())
        return
    
    await message.answer("Выберите привычку для удаления:", 
                        reply_markup=get_habits_keyboard(habits, "delete"))

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
    text += f"\n🔥 **Текущая серия:** {streak} дней"
    text += f"\n🎯 **Всего выполнено:** {total_done} раз"
    
    await message.answer(text, reply_markup=get_main_menu())

# === ОБРАБОТЧИКИ CALLBACK ===
@dp.callback_query(F.data.startswith("mark_"))
async def mark_habit_callback(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    await mark_done(habit_id, True)
    
    # Получаем название привычки для сообщения
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name FROM habits WHERE id=?", (habit_id,))
        habit_name = await cursor.fetchone()
    
    await callback.message.edit_text(f"✅ Привычка '{habit_name[0]}' отмечена как выполненная!")
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_"))
async def delete_habit_callback(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    
    # Получаем название привычки перед удалением
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT name FROM habits WHERE id=?", (habit_id,))
        habit_name = await cursor.fetchone()
    
    await delete_habit(habit_id, callback.from_user.id)
    await callback.message.edit_text(f"🗑 Привычка '{habit_name[0]}' удалена!")
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=get_main_menu())

# === НАПОМИНАНИЯ ===
async def send_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT user_id FROM habits")
        users = await cursor.fetchall()
    
    for (user_id,) in users:
        try:
            # Проверяем, есть ли неотмеченные привычки на сегодня
            today_progress = await get_today_progress(user_id)
            unmarked = [habit for habit in today_progress if not habit[3]]
            
            if unmarked:
                reminder_text = "🔔 **Напоминание!**\n\nНе забудьте отметить привычки за сегодня:\n"
                for habit in unmarked[:5]:  # Показываем максимум 5 привычек
                    reminder_text += f"• {habit[1]}\n"
                
                if len(unmarked) > 5:
                    reminder_text += f"• ... и еще {len(unmarked) - 5} привычек\n"
                
                reminder_text += "\nИспользуйте кнопку '✅ Отметить выполнение'"
                
                await bot.send_message(user_id, reminder_text, reply_markup=get_main_menu())
        except Exception as e:
            logging.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")

def setup_scheduler():
    scheduler.add_job(send_reminders, CronTrigger(hour=20, minute=0))  # ежедневно в 20:00
    scheduler.add_job(send_reminders, CronTrigger(hour=9, minute=0))   # ежедневно в 9:00
    scheduler.start()

# === MAIN ===
async def main():
    await init_db()
    setup_scheduler()
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())