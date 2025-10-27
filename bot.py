# bot.py
import asyncio
import logging
import os
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
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# ================= ENV & LOGGING =================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")  # mongodb+srv://user:pass@cluster/...
TZ_NAME = os.getenv("TZ", "Asia/Almaty")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в переменных окружения")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI не найден в переменных окружения")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("habitbot")

KZ_TZ = ZoneInfo(TZ_NAME)

# ================= AIROGRAM & SCHEDULER =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=KZ_TZ)

# ================= MONGO =================
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["habit_tracker_bot"]
col_habits = db["habits"]
col_records = db["records"]
col_settings = db["user_settings"]


async def create_indexes():
    # habits: частые выборки по user_id, сортировка по created_at
    await col_habits.create_index([("user_id", 1), ("created_at", -1)])
    # records: уникальная отметка в день по привычке
    await col_records.create_index([("habit_id", 1), ("date", 1)], unique=True)
    # user_settings: по user_id
    await col_settings.create_index([("user_id", 1)], unique=True)


# ================= FSM STATES =================
class HabitStates(StatesGroup):
    waiting_for_habit_name = State()


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
    habits: list[dict] с полями _id, name, color
    """
    keyboard = []
    for h in habits:
        hid = str(h["_id"])
        name = h.get("name", "Без названия")
        color = h.get("color", "🔵")
        cb = f"{'mark' if action_type == 'mark' else 'delete'}_{hid}"
        keyboard.append([InlineKeyboardButton(text=f"{color} {name}", callback_data=cb)])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ================= DATA ACCESS =================
def today_kz_date_str() -> str:
    return datetime.now(KZ_TZ).date().isoformat()


async def add_habit(user_id: int, name: str, color: str = "🔵"):
    doc = {
        "user_id": user_id,
        "name": name,
        "created_at": datetime.now(KZ_TZ),
        "color": color,
    }
    await col_habits.insert_one(doc)


async def get_habits(user_id: int):
    cursor = col_habits.find({"user_id": user_id}).sort("created_at", -1)
    return await cursor.to_list(length=None)


async def delete_habit(habit_id: str, user_id: int):
    # удаляем только запись владельца
    await col_habits.delete_one({"_id": ObjectId(habit_id), "user_id": user_id})
    await col_records.delete_many({"habit_id": habit_id})


async def mark_done(habit_id: str, done: bool = True):
    dstr = today_kz_date_str()
    await col_records.update_one(
        {"habit_id": habit_id, "date": dstr},
        {"$set": {"done": done}},
        upsert=True
    )


async def get_today_progress(user_id: int):
    """
    Возвращает список кортежей (habit_id, name, color, done: bool) на сегодня
    """
    dstr = today_kz_date_str()
    habits = await get_habits(user_id)
    result = []
    for h in habits:
        hid = str(h["_id"])
        rec = await col_records.find_one({"habit_id": hid, "date": dstr})
        result.append((hid, h.get("name", "Без названия"), h.get("color", "🔵"), bool(rec and rec.get("done"))))
    return result


async def get_stats(user_id: int, days: int = 7):
    """
    Возвращает список (name, color, total_done) за последние days
    """
    since = datetime.now(KZ_TZ).date() - timedelta(days=days)
    since_str = since.isoformat()
    # соберём все привычки пользователя
    habits = await get_habits(user_id)
    id2meta = {str(h["_id"]): (h.get("name", "Без названия"), h.get("color", "🔵")) for h in habits}
    # посчитаем done по каждой привычке
    pipeline = [
        {"$match": {"habit_id": {"$in": list(id2meta.keys())}, "date": {"$gte": since_str}, "done": True}},
        {"$group": {"_id": "$habit_id", "cnt": {"$sum": 1}}},
        {"$sort": {"cnt": -1}},
    ]
    agg = await col_records.aggregate(pipeline).to_list(length=None)
    # соберём ответ
    out = []
    for g in agg:
        hid = g["_id"]
        cnt = g["cnt"]
        name, color = id2meta.get(hid, ("(удалено)", "🔵"))
        out.append((name, color, cnt))
    # добавим привычки с нулём
    used = {g["_id"] for g in agg}
    for hid, (name, color) in id2meta.items():
        if hid not in used:
            out.append((name, color, 0))
    # отсортируем по убыванию
    out.sort(key=lambda x: x[2], reverse=True)
    return out


async def get_streak(user_id: int, habit_id: str | None = None):
    """
    Возвращает текущую серию подряд выполненных дней.
    Если habit_id = None — серия по всем привычкам (хотя бы одна выполнена в каждый день).
    """
    today = datetime.now(KZ_TZ).date()
    if habit_id:
        # Получаем все даты с done=True по конкретной привычке
        cursor = col_records.find({"habit_id": habit_id, "done": True}).sort("date", -1)
        dates = [r["date"] async for r in cursor]
        date_set = set(dates)
        streak = 0
        while True:
            d = (today - timedelta(days=streak)).isoformat()
            if d in date_set:
                streak += 1
            else:
                break
        return streak
    else:
        # По всем привычкам пользователя: «хотя бы одна выполнена в день»
        habits = await get_habits(user_id)
        ids = [str(h["_id"]) for h in habits]
        cursor = col_records.find({"habit_id": {"$in": ids}, "done": True})
        dates = {r["date"] async for r in cursor}
        streak = 0
        while True:
            d = (today - timedelta(days=streak)).isoformat()
            if d in dates:
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
    habits_today = await get_today_progress(message.from_user.id)
    if not habits_today:
        await message.answer("У вас пока нет привычек. Добавьте первую привычку!", reply_markup=get_main_menu())
        return

    today = datetime.now(KZ_TZ).strftime("%d.%m.%Y")
    text = f"📊 **Ваш прогресс на {today}:**\n\n"

    completed = 0
    for _, name, color, done in habits_today:
        status = "✅" if done else "⏳"
        text += f"{color} {name} — {status}\n"
        if done:
            completed += 1

    total = len(habits_today)
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
    habit_id = callback.data.split("_", 1)[1]
    await mark_done(habit_id, True)
    h = await col_habits.find_one({"_id": ObjectId(habit_id)})
    habit_name = (h or {}).get("name", "Привычка")
    await callback.message.edit_text(f"✅ Привычка «{habit_name}» отмечена как выполненная!")
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_"))
async def delete_habit_callback(callback: types.CallbackQuery):
    habit_id = callback.data.split("_", 1)[1]
    h = await col_habits.find_one({"_id": ObjectId(habit_id)})
    habit_name = (h or {}).get("name", "Привычка")
    await delete_habit(habit_id, callback.from_user.id)
    await callback.message.edit_text(f"🗑 Привычка «{habit_name}» удалена!")
    await callback.answer()


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=get_main_menu())


# ================= REMINDERS =================
async def send_reminders():
    # найдём всех пользователей, у которых есть привычки
    users = await col_habits.distinct("user_id")
    for user_id in users:
        try:
            today_progress = await get_today_progress(user_id)
            unmarked = [h for h in today_progress if not h[3]]
            if unmarked:
                reminder_text = "🔔 **Напоминание!**\n\nНе забудьте отметить привычки за сегодня:\n"
                for habit in unmarked[:5]:
                    _, name, color, _ = habit
                    reminder_text += f"• {color} {name}\n"
                if len(unmarked) > 5:
                    reminder_text += f"• ... и ещё {len(unmarked) - 5} привычек\n"
                reminder_text += "\nИспользуйте кнопку «✅ Отметить выполнение»"
                await bot.send_message(user_id, reminder_text, reply_markup=get_main_menu())
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")


def setup_scheduler():
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
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        await bot.session.close()
    except Exception:
        pass
    try:
        mongo_client.close()
    except Exception:
        pass
    logger.info("Бот корректно остановлен.")


# ================= MAIN =================
async def main():
    # На всякий случай, если когда-то был webhook
    await bot.delete_webhook(drop_pending_updates=True)

    await create_indexes()
    setup_scheduler()
    logger.info("Бот запущен!")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
