from __future__ import annotations

import random
from datetime import date
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..keyboards import habits_inline_keyboard, main_menu_keyboard
from ..services.habits import (
    get_user_settings,
    list_due_habits,
    mark_completed,
)
from ..utils.dates import tz_today


router = Router(name="mark")
settings = get_settings()


async def _user_zoneinfo(user_id: int) -> ZoneInfo:
    settings_doc = await get_user_settings(user_id)
    tz_name = settings_doc.get("timezone", settings.timezone)
    return ZoneInfo(tz_name)


@router.message(F.text == "✅ Отметить сегодня")
async def mark_today(message: Message) -> None:
    tz = await _user_zoneinfo(message.from_user.id)
    today = tz_today(tz)
    habits = await list_due_habits(message.from_user.id, on_date=today)
    if not habits:
        await message.answer(
            "На сегодня нет запланированных привычек или всё уже отмечено. Отличная работа!",
            reply_markup=main_menu_keyboard(),
        )
        return
    text = f"Выбери привычку, которую выполнил сегодня ({today.strftime('%d.%m')}):"
    await message.answer(text, reply_markup=habits_inline_keyboard(habits, "done"))


@router.callback_query(F.data.startswith("habit:done:"))
async def mark_done_callback(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 2)[2]
    tz = await _user_zoneinfo(callback.from_user.id)
    today = tz_today(tz)
    inserted, habit = await mark_completed(habit_id, callback.from_user.id, on_date=today)
    if not habit:
        await callback.answer("Не удалось найти привычку.")
        return
    if not inserted:
        await callback.answer("Уже было отмечено.")
        return
    text = f"{habit.get('emoji', '✅')} «{habit.get('name', 'Привычка')}» зачтена! Текущий стрик: {habit.get('current_streak', 1)}."
    await callback.message.answer(text, reply_markup=main_menu_keyboard())
    try:
        await callback.message.answer_animation(random.choice(settings.animation_urls))
    except Exception:
        pass
    await callback.answer("Отмечено!")

