from __future__ import annotations

import random

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..keyboards import main_menu_keyboard
from ..services.habits import ensure_user_settings
from ..texts import HELP_TEXT, WELCOME_TEXT


router = Router(name="start")
settings = get_settings()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await ensure_user_settings(message.from_user.id)
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    try:
        await message.answer_animation(random.choice(settings.animation_urls))
    except Exception:
        # Animation is optional; ignore failures (e.g., disabled media)
        pass


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())


@router.callback_query(lambda c: c.data in {"common:back", "common:back_habits"})
async def back_to_menu(callback: CallbackQuery) -> None:
    await callback.message.answer("Главное меню:", reply_markup=main_menu_keyboard())
    await callback.answer()

