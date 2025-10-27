from __future__ import annotations

import re
from typing import Dict, List
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..keyboards import (
    habit_details_keyboard,
    habits_inline_keyboard,
    main_menu_keyboard,
    reminder_menu_keyboard,
)
from ..services.habits import (
    archive_habit,
    completions_for_habit,
    get_habit,
    get_user_settings,
    list_active_habits,
    update_reminder,
)
from ..states import ReminderTimeUpdate
from ..utils.dates import format_display, parse_iso


router = Router(name="habits")
settings = get_settings()


async def _user_zoneinfo(user_id: int) -> ZoneInfo:
    settings_doc = await get_user_settings(user_id)
    tz_name = settings_doc.get("timezone", settings.timezone)
    return ZoneInfo(tz_name)


def _describe_repeat(habit: Dict) -> str:
    repeat = habit.get("repeat", {})
    mode = repeat.get("mode")
    if mode == "daily":
        return "Каждый день"
    if mode == "weekdays":
        labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        days = repeat.get("weekdays", [])
        if not days:
            return "По дням: ежедневно"
        return "По дням: " + ", ".join(labels[d] for d in days)
    if mode == "weekly":
        labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day = repeat.get("week_day", 0)
        return f"Каждую неделю ({labels[day]})"
    if mode == "monthly":
        return f"Раз в месяц ({repeat.get('month_day', 1)} число)"
    if mode == "interval":
        return f"Раз в {repeat.get('interval_days', 1)} дн."
    return "Гибкое расписание"


@router.message(F.text == "📅 Мои привычки")
async def habits_list(message: Message) -> None:
    habits = await list_active_habits(message.from_user.id)
    if not habits:
        await message.answer(
            "Пока нет активных привычек. Создай первую через «➕ Добавить привычку».",
            reply_markup=main_menu_keyboard(),
        )
        return
    await message.answer(
        "Выбери привычку, чтобы посмотреть детали или настроить напоминания:",
        reply_markup=habits_inline_keyboard(habits, "view"),
    )


@router.callback_query(F.data.startswith("habit:view:"))
async def habit_view(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 2)[2]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Не удалось найти привычку.")
        return
    tz = await _user_zoneinfo(callback.from_user.id)
    start = format_display(parse_iso(habit["start_date"]))
    target = habit.get("target_date")
    target_text = format_display(parse_iso(target)) if target else "Без срока"
    reminder = habit.get("reminder", {})
    reminder_text = "Выключено"
    if reminder.get("enabled"):
        reminder_text = f"Каждый день в {reminder.get('time', settings.default_reminder_time)}"

    last_done = habit.get("last_completed_on")
    if last_done:
        last_done = format_display(parse_iso(last_done))
    else:
        last_done = "ещё нет"

    text = (
        f"{habit.get('emoji', '✅')} *{habit.get('name', 'Привычка')}*\n"
        f"{habit.get('description', '—')}\n\n"
        f"*Старт:* {start}\n"
        f"*Цель:* {target_text}\n"
        f"*Расписание:* {_describe_repeat(habit)}\n"
        f"*Стрик:* {habit.get('current_streak', 0)} (лучший {habit.get('best_streak', 0)})\n"
        f"*Последнее выполнение:* {last_done}\n"
        f"*Напоминание:* {reminder_text}"
    )
    await callback.message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=habit_details_keyboard(habit),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("habit:reminder:menu:"))
async def habit_reminder_menu(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await callback.message.answer("Настройка напоминания:", reply_markup=reminder_menu_keyboard(habit))
    await callback.answer()


@router.callback_query(F.data.startswith("habit:reminder:toggle:"))
async def habit_reminder_toggle(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    reminder = habit.get("reminder", {})
    enabled = not reminder.get("enabled", False)
    updated = await update_reminder(habit_id, callback.from_user.id, enabled=enabled)
    if updated:
        msg = "Напоминание включено" if enabled else "Напоминание отключено"
        await callback.message.edit_reply_markup(reply_markup=reminder_menu_keyboard(updated))
        await callback.answer(msg)
    else:
        await callback.answer("Ошибка при обновлении")


@router.callback_query(F.data.startswith("habit:reminder:time:"))
async def habit_reminder_time(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await state.set_state(ReminderTimeUpdate.waiting_time)
    await state.update_data(habit_id=habit_id)
    await callback.message.answer("Введи новое время напоминания (ЧЧ:ММ).")
    await callback.answer()


@router.message(ReminderTimeUpdate.waiting_time)
async def habit_reminder_time_set(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", text):
        await message.answer("Формат времени ЧЧ:ММ, пример 09:30.")
        return
    data = await state.get_data()
    habit_id = data.get("habit_id")
    await update_reminder(habit_id, message.from_user.id, reminder_time=text, enabled=True)
    habit = await get_habit(habit_id, message.from_user.id)
    await state.clear()
    if habit:
        await message.answer(
            f"Время напоминания обновлено на {text}.",
            reply_markup=reminder_menu_keyboard(habit),
        )
    else:
        await message.answer("Готово.", reply_markup=main_menu_keyboard())


@router.callback_query(F.data.startswith("habit:archive:"))
async def habit_archive(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 2)[2]
    success = await archive_habit(habit_id, callback.from_user.id)
    if success:
        await callback.message.answer("Привычка перенесена в архив.", reply_markup=main_menu_keyboard())
        await callback.answer("Архивировано")
    else:
        await callback.answer("Не удалось архивировать привычку.")


@router.callback_query(F.data.startswith("habit:stats:"))
async def habit_stats(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 2)[2]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Не удалось найти привычку.")
        return
    completions = await completions_for_habit(habit["_id"])
    if not completions:
        await callback.message.answer("Пока нет отметок по этой привычке.", reply_markup=main_menu_keyboard())
        await callback.answer()
        return
    last_entries = completions[-10:]
    formatted = [format_display(parse_iso(day)) for day in last_entries]
    stats_text = (
        f"{habit.get('emoji', '✅')} *{habit.get('name', 'Привычка')}*\n"
        f"Всего выполнений: {len(completions)}\n"
        f"Текущий стрик: {habit.get('current_streak', 0)} / Лучший: {habit.get('best_streak', 0)}\n"
        f"Последние отметки: " + ", ".join(formatted)
    )
    await callback.message.answer(stats_text, parse_mode="Markdown", reply_markup=habit_details_keyboard(habit))
    await callback.answer()
