from __future__ import annotations

import re
from typing import Dict, List
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..keyboards import (
    delete_confirmation_keyboard,
    habit_details_keyboard,
    habit_edit_keyboard,
    emoji_keyboard,
    habits_inline_keyboard,
    main_menu_keyboard,
    navigation_keyboard,
    reminder_menu_keyboard,
    with_navigation,
)
from ..services.habits import (
    archive_habit,
    completions_for_habit,
    delete_habit_permanently,
    get_habit,
    get_user_settings,
    list_active_habits,
    update_habit_fields,
    update_reminder,
)
from ..states import EditHabit, ReminderTimeUpdate
from ..utils.dates import format_display, parse_iso


router = Router(name="habits")
settings = get_settings()

CANCEL_KEYWORDS = {"отмена", "cancel", "стоп"}


def _is_cancel(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in CANCEL_KEYWORDS


def _habit_details_text(habit: Dict) -> str:
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

    description = habit.get("description", "").strip() or "—"

    return (
        f"{habit.get('emoji', '✅')} *{habit.get('name', 'Привычка')}*\n"
        f"{description}\n\n"
        f"*Старт:* {start}\n"
        f"*Цель:* {target_text}\n"
        f"*Расписание:* {_describe_repeat(habit)}\n"
        f"*Стрик:* {habit.get('current_streak', 0)} (лучший {habit.get('best_streak', 0)})\n"
        f"*Последнее выполнение:* {last_done}\n"
        f"*Напоминание:* {reminder_text}"
    )


async def _send_habit_details(
    message: Message,
    habit_id: str,
    user_id: int,
    *,
    habit: Dict | None = None,
    notice: str | None = None,
) -> None:
    habit_doc = habit or await get_habit(habit_id, user_id)
    if not habit_doc:
        await message.answer("Привычка не найдена.", reply_markup=main_menu_keyboard())
        return
    text = _habit_details_text(habit_doc)
    if notice:
        text = f"{notice}\n\n{text}"
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=habit_details_keyboard(habit_doc),
    )


async def _send_edit_menu(
    message: Message,
    habit_id: str,
    user_id: int,
    *,
    habit: Dict | None = None,
    notice: str | None = None,
) -> None:
    habit_doc = habit or await get_habit(habit_id, user_id)
    if not habit_doc:
        await message.answer("Привычка не найдена.", reply_markup=main_menu_keyboard())
        return
    text = _habit_details_text(habit_doc)
    if notice:
        text = f"{notice}\n\n{text}"
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=habit_edit_keyboard(habit_id),
    )


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
async def habit_view(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 2)[2]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Не удалось найти привычку.")
        return
    await state.clear()
    await _send_habit_details(callback.message, habit_id, callback.from_user.id, habit=habit)
    await callback.answer()


@router.callback_query(F.data.startswith("habit:edit:menu:"))
async def habit_edit_menu(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await state.clear()
    await _send_edit_menu(
        callback.message,
        habit_id,
        callback.from_user.id,
        habit=habit,
        notice="Что изменить?",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("habit:edit:name:"))
async def habit_edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await state.set_state(EditHabit.waiting_name)
    await state.update_data(habit_id=habit_id)
    await callback.message.answer(
        "Введи новое название (минимум 2 символа).",
        reply_markup=navigation_keyboard(
            cancel_cb=f"habit:view:{habit_id}",
            back_cb=f"habit:edit:menu:{habit_id}",
        ),
    )
    await callback.answer()


@router.message(EditHabit.waiting_name)
async def habit_edit_name_set(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    habit_id = data.get("habit_id")
    if not habit_id:
        await state.clear()
        await message.answer("Сессия редактирования истекла.", reply_markup=main_menu_keyboard())
        return
    if _is_cancel(message.text):
        await state.clear()
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            notice="Редактирование отменено.",
        )
        return
    new_name = (message.text or "").strip()
    if len(new_name) < 2:
        await message.answer(
            "Название слишком короткое, нужно минимум 2 символа.",
            reply_markup=navigation_keyboard(
                cancel_cb=f"habit:view:{habit_id}",
                back_cb=f"habit:edit:menu:{habit_id}",
            ),
        )
        return
    updated = await update_habit_fields(habit_id, message.from_user.id, name=new_name)
    habit = await get_habit(habit_id, message.from_user.id)
    await state.clear()
    if updated and habit:
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            habit=habit,
            notice="Название обновлено ✅",
        )
    else:
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            habit=habit,
            notice="Не удалось обновить название.",
        )


@router.callback_query(F.data.startswith("habit:edit:description:"))
async def habit_edit_description(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await state.set_state(EditHabit.waiting_description)
    await state.update_data(habit_id=habit_id)
    await callback.message.answer(
        "Отправь новое описание или напиши «Отмена». Пустое сообщение очистит описание.",
        reply_markup=navigation_keyboard(
            cancel_cb=f"habit:view:{habit_id}",
            back_cb=f"habit:edit:menu:{habit_id}",
        ),
    )
    await callback.answer()


@router.message(EditHabit.waiting_description)
async def habit_edit_description_set(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    habit_id = data.get("habit_id")
    if not habit_id:
        await state.clear()
        await message.answer("Сессия редактирования истекла.", reply_markup=main_menu_keyboard())
        return
    if _is_cancel(message.text):
        await state.clear()
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            notice="Редактирование отменено.",
        )
        return
    new_description = (message.text or "").strip()
    updated = await update_habit_fields(
        habit_id,
        message.from_user.id,
        description=new_description,
    )
    habit = await get_habit(habit_id, message.from_user.id)
    await state.clear()
    if updated and habit is not None:
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            habit=habit,
            notice="Описание обновлено ✅",
        )
    else:
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            habit=habit,
            notice="Не удалось обновить описание.",
        )


@router.callback_query(F.data.startswith("habit:edit:emoji:"))
async def habit_edit_emoji(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 3)[3]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await state.set_state(EditHabit.waiting_emoji)
    await state.update_data(habit_id=habit_id)
    await callback.message.answer(
        "Выбери новое эмодзи или отправь своё сообщением.",
        reply_markup=with_navigation(
            emoji_keyboard(prefix=f"habit:emoji:{habit_id}"),
            cancel_cb=f"habit:view:{habit_id}",
            back_cb=f"habit:edit:menu:{habit_id}",
        ),
    )
    await callback.answer()


@router.callback_query(EditHabit.waiting_emoji, F.data.startswith("habit:emoji:"))
async def habit_edit_emoji_pick(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":", 3)
    if len(parts) < 4:
        await callback.answer()
        return
    _, _, habit_id, value = parts
    if value == "custom":
        await callback.message.answer(
            "Отправь эмодзи сообщением.",
            reply_markup=navigation_keyboard(
                cancel_cb=f"habit:view:{habit_id}",
                back_cb=f"habit:edit:menu:{habit_id}",
            ),
        )
        await callback.answer()
        return
    emoji_value = value[:2]
    updated = await update_habit_fields(habit_id, callback.from_user.id, emoji=emoji_value)
    habit = await get_habit(habit_id, callback.from_user.id)
    await state.clear()
    if updated and habit:
        await _send_edit_menu(
            callback.message,
            habit_id,
            callback.from_user.id,
            habit=habit,
            notice="Эмодзи обновлено ✅",
        )
        await callback.answer("Обновлено")
    else:
        await _send_edit_menu(
            callback.message,
            habit_id,
            callback.from_user.id,
            habit=habit,
            notice="Не удалось обновить эмодзи.",
        )
        await callback.answer("Ошибка")


@router.message(EditHabit.waiting_emoji)
async def habit_edit_emoji_manual(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    habit_id = data.get("habit_id")
    if not habit_id:
        await state.clear()
        await message.answer("Сессия редактирования истекла.", reply_markup=main_menu_keyboard())
        return
    if _is_cancel(message.text):
        await state.clear()
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            notice="Редактирование отменено.",
        )
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer(
            "Отправь хотя бы один символ.",
            reply_markup=navigation_keyboard(
                cancel_cb=f"habit:view:{habit_id}",
                back_cb=f"habit:edit:menu:{habit_id}",
            ),
        )
        return
    emoji_value = value[:2]
    updated = await update_habit_fields(habit_id, message.from_user.id, emoji=emoji_value)
    habit = await get_habit(habit_id, message.from_user.id)
    await state.clear()
    if updated and habit:
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            habit=habit,
            notice="Эмодзи обновлено ✅",
        )
    else:
        await _send_edit_menu(
            message,
            habit_id,
            message.from_user.id,
            habit=habit,
            notice="Не удалось обновить эмодзи.",
        )


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


@router.callback_query(
    F.data.startswith("habit:delete:") & ~F.data.startswith("habit:delete:confirm:")
)
async def habit_delete(callback: CallbackQuery) -> None:
    habit_id = callback.data.split(":", 2)[2]
    habit = await get_habit(habit_id, callback.from_user.id)
    if not habit:
        await callback.answer("Привычка не найдена")
        return
    await callback.message.answer(
        "Удалить привычку навсегда? Это действие нельзя отменить.",
        reply_markup=delete_confirmation_keyboard(habit_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("habit:delete:confirm:"))
async def habit_delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    habit_id = callback.data.split(":", 3)[3]
    success = await delete_habit_permanently(habit_id, callback.from_user.id)
    await state.clear()
    if success:
        await callback.message.answer(
            "Привычка удалена полностью.",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer("Удалено")
    else:
        await callback.answer("Не удалось удалить привычку.")


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
