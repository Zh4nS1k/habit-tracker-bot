from __future__ import annotations

import re
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import get_settings
from ..keyboards import main_menu_keyboard
from ..services.habits import get_user_settings, update_user_settings
from ..states import SettingsReminder, TimezoneUpdate


router = Router(name="settings")
settings = get_settings()
TIME_RX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DEFAULT_TIMEZONES: Sequence[str] = (
    "Asia/Almaty",
    "Asia/Aqtau",
    "Asia/Bishkek",
    "Asia/Tashkent",
    "Europe/Moscow",
    "Europe/Berlin",
)


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Изменить часовой пояс", callback_data="settings:timezone")],
            [InlineKeyboardButton(text="⏰ Время напоминаний", callback_data="settings:reminder")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="common:back")],
        ]
    )


def timezone_select_keyboard(current: str) -> InlineKeyboardMarkup:
    rows = []
    for tz in DEFAULT_TIMEZONES:
        mark = "✅ " if tz == current else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{tz}", callback_data=f"settings:timezone:{tz}")])
    rows.append([InlineKeyboardButton(text="🌐 Другое", callback_data="settings:timezone:other")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "⚙️ Настройки")
async def settings_entry(message: Message) -> None:
    doc = await get_user_settings(message.from_user.id)
    tz = doc.get("timezone", settings.timezone)
    reminder_time = doc.get("default_reminder_time", settings.default_reminder_time)
    text = (
        "⚙️ *Настройки*\n\n"
        f"• Часовой пояс: {tz}\n"
        f"• Время напоминаний по умолчанию: {reminder_time}\n\n"
        "Можно изменить часовой пояс или базовое время напоминаний."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=settings_keyboard())


@router.callback_query(F.data == "settings:timezone")
async def settings_timezone(callback: CallbackQuery) -> None:
    doc = await get_user_settings(callback.from_user.id)
    tz = doc.get("timezone", settings.timezone)
    await callback.message.answer("Выбери часовой пояс:", reply_markup=timezone_select_keyboard(tz))
    await callback.answer()


@router.callback_query(F.data == "settings:back")
async def settings_back(callback: CallbackQuery) -> None:
    doc = await get_user_settings(callback.from_user.id)
    tz = doc.get("timezone", settings.timezone)
    reminder_time = doc.get("default_reminder_time", settings.default_reminder_time)
    text = (
        "⚙️ *Настройки*\n\n"
        f"• Часовой пояс: {tz}\n"
        f"• Время напоминаний по умолчанию: {reminder_time}\n\n"
        "Можно изменить часовой пояс или базовое время напоминаний."
    )
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=settings_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("settings:timezone:"))
async def settings_timezone_select(callback: CallbackQuery, state: FSMContext) -> None:
    tz_value = callback.data.split(":", 2)[2]
    if tz_value == "other":
        await state.set_state(TimezoneUpdate.waiting_timezone)
        await callback.message.answer("Введи часовой пояс в формате Region/City (например, Europe/Berlin).")
        await callback.answer()
        return
    try:
        ZoneInfo(tz_value)
    except ZoneInfoNotFoundError:
        await callback.answer("Неверный часовой пояс.")
        return
    await update_user_settings(callback.from_user.id, timezone=tz_value)
    await callback.message.answer(f"Часовой пояс обновлён на {tz_value}.", reply_markup=settings_keyboard())
    await callback.answer("Сохранено")


@router.message(TimezoneUpdate.waiting_timezone)
async def settings_timezone_manual(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        await message.answer("Не удалось распознать часовой пояс. Пример: Asia/Almaty.")
        return
    await update_user_settings(message.from_user.id, timezone=value)
    await state.clear()
    await message.answer(f"Часовой пояс обновлён на {value}.", reply_markup=settings_keyboard())


@router.callback_query(F.data == "settings:reminder")
async def settings_reminder(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsReminder.waiting_time)
    await callback.message.answer("Введи время напоминаний по умолчанию (ЧЧ:ММ).")
    await callback.answer()


@router.message(SettingsReminder.waiting_time)
async def settings_reminder_time(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not TIME_RX.match(value):
        await message.answer("Время должно быть в формате ЧЧ:ММ, пример 20:30.")
        return
    await update_user_settings(message.from_user.id, default_reminder_time=value)
    await state.clear()
    await message.answer(f"Время напоминаний по умолчанию установлено на {value}.", reply_markup=settings_keyboard())
