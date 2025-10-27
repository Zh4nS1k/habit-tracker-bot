from __future__ import annotations

import random
import re
from datetime import date, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..keyboards import (
    confirmation_keyboard,
    emoji_keyboard,
    main_menu_keyboard,
    reminder_initial_keyboard,
    reminder_time_entry_keyboard,
    repeat_mode_keyboard,
    navigation_keyboard,
    with_navigation,
    skip_keyboard,
    start_date_keyboard,
    target_date_keyboard,
    weekdays_keyboard,
)
from ..services.habits import create_habit, get_user_settings
from ..states import CreateHabit
from ..texts import CREATE_PROMPT
from ..utils.dates import as_iso, format_display, parse_iso, parse_user_date


router = Router(name="create_habit")
settings = get_settings()
TIME_RX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
CANCEL_KEYWORDS = {"отмена", "cancel", "стоп"}


async def _user_zoneinfo(user_id: int) -> ZoneInfo:
    info = await get_user_settings(user_id)
    tz_name = info.get("timezone", settings.timezone)
    return ZoneInfo(tz_name)


def _is_cancel(text: Optional[str]) -> bool:
    return bool(text) and text.strip().lower() in CANCEL_KEYWORDS


async def _cancel_creation(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание привычки отменено.", reply_markup=main_menu_keyboard())


async def _ask_name(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_name)
    await message.answer(
        CREATE_PROMPT,
        reply_markup=navigation_keyboard(),
    )


async def _ask_emoji(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_emoji)
    await message.answer(
        "Выбери эмодзи, которое будем показывать рядом с привычкой:",
        reply_markup=with_navigation(emoji_keyboard(), back_cb="create:back:name"),
    )


async def _ask_description(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_description)
    await message.answer(
        "Добавь короткое описание (например, цель или триггер) или пропусти шаг.",
        reply_markup=with_navigation(skip_keyboard("create:description:skip"), back_cb="create:back:emoji"),
    )


async def _ask_start_date(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_start)
    await message.answer(
        "Когда стартуем?",
        reply_markup=with_navigation(start_date_keyboard(), back_cb="create:back:description"),
    )


async def _ask_target_date(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_target)
    await message.answer(
        "Нужно задать дату завершения привычки? Это опционально.",
        reply_markup=with_navigation(target_date_keyboard(), back_cb="create:back:start"),
    )


async def _ask_repeat_mode(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_repeat_mode)
    await message.answer(
        "Выбери, как часто повторять привычку:",
        reply_markup=with_navigation(repeat_mode_keyboard(), back_cb="create:back:target"),
    )


async def _ask_reminder(message: Message, state: FSMContext) -> None:
    await state.set_state(CreateHabit.waiting_reminder_toggle)
    await message.answer(
        "Нужно ли напоминание?",
        reply_markup=with_navigation(reminder_initial_keyboard(), back_cb="create:back:repeat"),
    )


def _describe_repeat(repeat: Dict) -> str:
    mode = repeat.get("mode")
    if mode == "daily":
        return "Каждый день"
    if mode == "weekdays":
        weekdays = repeat.get("weekdays", [])
        titles = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        selected = [titles[i] for i in weekdays]
        return "По дням: " + ", ".join(selected)
    if mode == "weekly":
        titles = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        day = repeat.get("week_day", 0)
        return f"Каждую неделю ({titles[day]})"
    if mode == "monthly":
        return f"Раз в месяц ({repeat.get('month_day', 1)} число)"
    if mode == "interval":
        return f"Раз в {repeat.get('interval_days', 1)} дн."
    return "Гибкое расписание"


def _build_summary(data: Dict) -> str:
    start = format_display(parse_iso(data["start_date"]))
    target = data.get("target_date")
    if target:
        target_text = format_display(parse_iso(target))
    else:
        target_text = "Без срока"

    reminder_enabled = data.get("reminder_enabled", False)
    reminder_line = "Нет"
    if reminder_enabled:
        reminder_line = f"Ежедневно в {data.get('reminder_time', settings.default_reminder_time)}"

    description = data.get("description", "").strip()
    if not description:
        description = "—"

    repeat = data.get("repeat", {})

    return (
        f"{data.get('emoji', '✅')} *{data.get('name', 'Привычка')}*\n"
        f"{description}\n\n"
        f"*Старт:* {start}\n"
        f"*Цель:* {target_text}\n"
        f"*Повтор:* {_describe_repeat(repeat)}\n"
        f"*Напоминание:* {reminder_line}"
    )


@router.message(F.text == "➕ Добавить привычку")
async def create_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _ask_name(message, state)


@router.message(CreateHabit.waiting_name)
async def create_set_name(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Название должно содержать хотя бы 2 символа, попробуй ещё раз.",
            reply_markup=navigation_keyboard(),
        )
        return
    await state.update_data(name=name)
    await _ask_emoji(message, state)


@router.callback_query(CreateHabit.waiting_emoji, F.data.startswith("create:emoji:"))
async def create_pick_emoji(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, value = callback.data.split(":", 2)
    if value == "custom":
        await state.set_state(CreateHabit.waiting_emoji)
        await callback.message.answer(
            "Отправь любое эмодзи или символ, который будем использовать.",
            reply_markup=navigation_keyboard(back_cb="create:back:emoji"),
        )
        await callback.answer()
        return
    await state.update_data(emoji=value)
    await _ask_description(callback.message, state)
    await callback.answer()


@router.message(CreateHabit.waiting_emoji)
async def create_custom_emoji(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    value = (message.text or "").strip()
    if not value:
        await message.answer(
            "Пришли хотя бы один символ или воспользуйся кнопками.",
            reply_markup=navigation_keyboard(back_cb="create:back:emoji"),
        )
        return
    await state.update_data(emoji=value[:2])
    await _ask_description(message, state)


@router.callback_query(CreateHabit.waiting_description, F.data == "create:description:skip")
async def create_description_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(description="")
    await _ask_start_date(callback.message, state)
    await callback.answer()


@router.message(CreateHabit.waiting_description)
async def create_set_description(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    await state.update_data(description=(message.text or "").strip())
    await _ask_start_date(message, state)

@router.callback_query(CreateHabit.waiting_start, F.data.startswith("create:start:"))
async def create_start_date_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, choice = callback.data.split(":", 2)
    tz = await _user_zoneinfo(callback.from_user.id)
    today = parse_user_date("сегодня", tz)
    assert today is not None
    if choice == "today":
        await state.update_data(start_date=as_iso(today))
        await _ask_target_date(callback.message, state)
    elif choice == "tomorrow":
        await state.update_data(start_date=as_iso(today + timedelta(days=1)))
        await _ask_target_date(callback.message, state)
    elif choice == "manual":
        await callback.message.answer(
            "Введи дату в формате ДД.ММ или ДД.ММ.ГГГГ.",
            reply_markup=navigation_keyboard(back_cb="create:back:start"),
        )
    await callback.answer()


@router.message(CreateHabit.waiting_start)
async def create_start_date_manual(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    tz = await _user_zoneinfo(message.from_user.id)
    parsed = parse_user_date(message.text or "", tz)
    if not parsed:
        await message.answer(
            "Не смог распознать дату. Попробуй формат ДД.ММ.ГГГГ.",
            reply_markup=navigation_keyboard(back_cb="create:back:start"),
        )
        return
    await state.update_data(start_date=as_iso(parsed))
    await _ask_target_date(message, state)


@router.callback_query(CreateHabit.waiting_target, F.data.startswith("create:target:"))
async def create_target_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, choice = callback.data.split(":", 2)
    if choice == "none":
        await state.update_data(target_date=None)
        await _ask_repeat_mode(callback.message, state)
    elif choice == "manual":
        await callback.message.answer(
            "Введи дату завершения в формате ДД.ММ.ГГГГ или нажми «Без срока».",
            reply_markup=navigation_keyboard(back_cb="create:back:target"),
        )
    await callback.answer()


@router.message(CreateHabit.waiting_target)
async def create_target_manual(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    data = await state.get_data()
    start_iso = data.get("start_date")
    if not start_iso:
        await message.answer(
            "Сначала выбери дату начала привычки.",
            reply_markup=with_navigation(start_date_keyboard(), back_cb="create:back:description"),
        )
        await state.set_state(CreateHabit.waiting_start)
        return
    start = parse_iso(start_iso)
    tz = await _user_zoneinfo(message.from_user.id)
    parsed = parse_user_date(message.text or "", tz)
    if not parsed:
        await message.answer(
            "Дата не распознана, попробуй формат ДД.ММ.ГГГГ.",
            reply_markup=navigation_keyboard(back_cb="create:back:target"),
        )
        return
    if parsed < start:
        await message.answer(
            "Дата завершения не может быть раньше старта.",
            reply_markup=navigation_keyboard(back_cb="create:back:target"),
        )
        return
    await state.update_data(target_date=as_iso(parsed))
    await _ask_repeat_mode(message, state)


@router.callback_query(CreateHabit.waiting_repeat_mode, F.data.startswith("create:repeat:"))
async def create_repeat_mode(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, mode = callback.data.split(":", 2)
    await state.update_data(repeat_mode=mode, repeat=None)
    if mode == "daily":
        await state.update_data(repeat={"mode": "daily"})
        await _ask_reminder(callback.message, state)
    elif mode == "weekdays":
        defaults = [0, 1, 2, 3, 4]
        await state.update_data(selected_weekdays=defaults, repeat={"mode": "weekdays", "weekdays": defaults})
        await state.set_state(CreateHabit.waiting_repeat_payload)
        await callback.message.answer(
            "Выбери дни недели, когда будем выполнять привычку:",
            reply_markup=with_navigation(weekdays_keyboard(defaults), back_cb="create:back:repeat"),
        )
    elif mode == "weekly":
        await state.update_data(selected_weekdays=[])
        await state.set_state(CreateHabit.waiting_repeat_payload)
        await callback.message.answer(
            "Выбери день недели (один):",
            reply_markup=with_navigation(weekdays_keyboard([]), back_cb="create:back:repeat"),
        )
    elif mode == "monthly":
        await state.set_state(CreateHabit.waiting_repeat_payload)
        await callback.message.answer(
            "Укажи число месяца (1-31).",
            reply_markup=navigation_keyboard(back_cb="create:back:repeat"),
        )
    elif mode == "interval":
        await state.set_state(CreateHabit.waiting_repeat_payload)
        await callback.message.answer(
            "Через сколько дней повторять? Введи число, например 2.",
            reply_markup=navigation_keyboard(back_cb="create:back:repeat"),
        )
    await callback.answer()


@router.callback_query(CreateHabit.waiting_repeat_payload, F.data.startswith("create:weekday:"))
async def create_weekday_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, value = callback.data.split(":", 2)
    data = await state.get_data()
    mode = data.get("repeat_mode")
    selected: List[int] = data.get("selected_weekdays", [])
    if value == "done":
        if mode == "weekdays":
            if not selected:
                await callback.answer("Нужно выбрать хотя бы один день.")
                return
            await state.update_data(repeat={"mode": "weekdays", "weekdays": selected})
        elif mode == "weekly":
            if len(selected) != 1:
                await callback.answer("Выбери ровно один день.")
                return
            await state.update_data(repeat={"mode": "weekly", "week_day": selected[0]})
        await _ask_reminder(callback.message, state)
        await callback.answer()
        return

    weekday = int(value)
    if mode == "weekly":
        selected = [weekday]
    else:
        if weekday in selected:
            selected.remove(weekday)
        else:
            selected.append(weekday)
        selected.sort()
    await state.update_data(selected_weekdays=selected)
    await callback.message.edit_reply_markup(
        reply_markup=with_navigation(weekdays_keyboard(selected), back_cb="create:back:repeat")
    )
    await callback.answer()


@router.message(CreateHabit.waiting_repeat_payload)
async def create_repeat_payload_text(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    data = await state.get_data()
    mode = data.get("repeat_mode")
    text = (message.text or "").strip()
    if mode == "interval":
        if not text.isdigit() or int(text) < 1 or int(text) > 30:
            await message.answer(
                "Нужно число от 1 до 30.",
                reply_markup=navigation_keyboard(back_cb="create:back:repeat"),
            )
            return
        interval = int(text)
        await state.update_data(repeat={"mode": "interval", "interval_days": interval})
        await _ask_reminder(message, state)
    elif mode == "monthly":
        if not text.isdigit():
            await message.answer(
                "Укажи число месяца от 1 до 31.",
                reply_markup=navigation_keyboard(back_cb="create:back:repeat"),
            )
            return
        day = int(text)
        if not 1 <= day <= 31:
            await message.answer(
                "Число месяца должно быть от 1 до 31.",
                reply_markup=navigation_keyboard(back_cb="create:back:repeat"),
            )
            return
        await state.update_data(repeat={"mode": "monthly", "month_day": day})
        await _ask_reminder(message, state)
    else:
        await message.answer(
            "Используй кнопки выбора.", reply_markup=navigation_keyboard(back_cb="create:back:repeat")
        )


@router.callback_query(CreateHabit.waiting_reminder_toggle, F.data.startswith("create:reminder:"))
async def create_reminder_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, choice = callback.data.split(":", 3)
    if choice == "on":
        user_settings = await get_user_settings(callback.from_user.id)
        default_time = user_settings.get("default_reminder_time", settings.default_reminder_time)
        await state.update_data(
            reminder_enabled=True,
            reminder_default_time=default_time,
        )
        await state.set_state(CreateHabit.waiting_reminder_time)
        await callback.message.answer(
            "Во сколько отправлять напоминание? Формат ЧЧ:ММ.",
            reply_markup=reminder_time_entry_keyboard(default_time),
        )
    else:
        await state.update_data(reminder_enabled=False, reminder_time=None)
        await _show_summary(callback.message, state)
    await callback.answer()


@router.callback_query(CreateHabit.waiting_reminder_time, F.data == "create:reminder:default")
async def create_reminder_default(callback: CallbackQuery, state: FSMContext) -> None:
    user_settings = await get_user_settings(callback.from_user.id)
    default_time = user_settings.get("default_reminder_time", settings.default_reminder_time)
    await state.update_data(reminder_time=default_time)
    await _show_summary(callback.message, state)
    await callback.answer("Используем время по умолчанию")


@router.callback_query(CreateHabit.waiting_reminder_time, F.data == "create:reminder:cancel")
async def create_reminder_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(reminder_enabled=None, reminder_time=None)
    await _ask_reminder(callback.message, state)
    await callback.answer()


@router.message(CreateHabit.waiting_reminder_time)
async def create_reminder_time(message: Message, state: FSMContext) -> None:
    if _is_cancel(message.text):
        await _cancel_creation(message, state)
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    default_time = data.get("reminder_default_time", settings.default_reminder_time)
    if not TIME_RX.match(text):
        await message.answer(
            "Введи время в формате ЧЧ:ММ (например 08:30).",
            reply_markup=reminder_time_entry_keyboard(default_time),
        )
        return
    await state.update_data(reminder_time=text)
    await _show_summary(message, state)


@router.callback_query(F.data == "create:cancel")
async def create_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _cancel_creation(callback.message, state)
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("create:back:"))
async def create_back_callback(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.split(":", 2)[2]
    if target == "name":
        await state.update_data(
            name=None,
            emoji=None,
            description="",
            start_date=None,
            target_date=None,
            repeat=None,
            repeat_mode=None,
            selected_weekdays=[],
            reminder_enabled=None,
            reminder_time=None,
            reminder_default_time=None,
        )
        await _ask_name(callback.message, state)
    elif target == "emoji":
        await state.update_data(emoji=None)
        await _ask_emoji(callback.message, state)
    elif target == "description":
        await state.update_data(description="")
        await _ask_description(callback.message, state)
    elif target == "start":
        await state.update_data(start_date=None, target_date=None, repeat=None, repeat_mode=None, selected_weekdays=[])
        await _ask_start_date(callback.message, state)
    elif target == "target":
        await state.update_data(target_date=None, repeat=None, repeat_mode=None, selected_weekdays=[])
        await _ask_target_date(callback.message, state)
    elif target == "repeat":
        await state.update_data(repeat=None, repeat_mode=None, selected_weekdays=[])
        await _ask_repeat_mode(callback.message, state)
    elif target == "reminder":
        await state.update_data(reminder_enabled=None, reminder_time=None, reminder_default_time=None)
        await _ask_reminder(callback.message, state)
    else:
        await callback.answer()
        return
    await callback.answer()


async def _show_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    repeat = data.get("repeat")
    if not repeat:
        await message.answer("Не удалось собрать данные по расписанию. Попробуем заново?", reply_markup=main_menu_keyboard())
        await state.clear()
        return
    await state.set_state(CreateHabit.waiting_confirmation)
    await message.answer(
        "Вот что получилось:\n\n" + _build_summary(data),
        parse_mode="Markdown",
        reply_markup=confirmation_keyboard(),
    )


@router.callback_query(CreateHabit.waiting_confirmation, F.data.startswith("create:confirm:"))
async def create_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, choice = callback.data.split(":", 2)
    if choice == "no":
        await state.clear()
        await callback.message.answer("Ок, начнём заново. Нажми «➕ Добавить привычку», когда будешь готов.")
        await callback.answer()
        return

    data = await state.get_data()
    start = parse_iso(data["start_date"])
    target = data.get("target_date")
    target_date = parse_iso(target) if target else None

    habit = await create_habit(
        user_id=callback.from_user.id,
        name=data.get("name"),
        emoji=data.get("emoji", "✅"),
        description=data.get("description", ""),
        start_date=start,
        target_date=target_date,
        repeat=data.get("repeat", {"mode": "daily"}),
        reminder_enabled=data.get("reminder_enabled", False),
        reminder_time=data.get("reminder_time"),
    )
    await state.clear()
    await callback.message.answer(
        f"Готово! Привычка «{habit['name']}» создана. Держу курс на новые рекорды ⭐️",
        reply_markup=main_menu_keyboard(),
    )
    try:
        await callback.message.answer_animation(random.choice(settings.animation_urls))
    except Exception:
        pass
    await callback.answer("Сохранено!")
