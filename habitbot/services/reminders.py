from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram import Bot

from ..config import get_settings
from ..db import col_habits
from ..models import HabitDocument
from ..utils.dates import as_iso, format_display, tz_now, utcnow
from .habits import (
    get_user_settings,
    has_completion_on_date,
    list_active_habits,
)
from ..utils.dates import is_due_on  # type: ignore  # circular import guard
from ..keyboards import main_menu_keyboard


log = logging.getLogger("habitbot.reminders")
settings = get_settings()


class ReminderService:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._runner())
        log.info("Reminder service started")

    async def stop(self) -> None:
        if not self._task:
            return
        if self._stop_event:
            self._stop_event.set()
        try:
            await self._task
        finally:
            self._task = None
            self._stop_event = None
            log.info("Reminder service stopped")

    async def _runner(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Reminder tick failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(10, settings.reminder_interval_seconds),
                )
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> None:
        user_ids = await col_habits.distinct(
            "user_id", {"archived": {"$ne": True}, "reminder.enabled": True}
        )
        for user_id in user_ids:
            user_settings = await get_user_settings(user_id)
            tz_name = user_settings.get("timezone", settings.timezone)
            tz = ZoneInfo(tz_name)
            now_local = tz_now(tz)
            today_local = now_local.date()
            time_now = now_local.strftime("%H:%M")

            habits = await list_active_habits(user_id)
            for habit in habits:
                reminder = habit.get("reminder", {})
                if not reminder or not reminder.get("enabled"):
                    continue
                reminder_time = reminder.get("time", settings.default_reminder_time)
                if reminder_time > time_now:
                    continue
                if reminder.get("last_sent_date") == as_iso(today_local):
                    continue
                if not is_due_on(habit, today_local):
                    continue
                if await has_completion_on_date(habit["_id"], user_id, today_local):
                    continue
                await self._send_reminder(user_id, habit, today_local)
                await col_habits.update_one(
                    {"_id": habit["_id"]},
                    {
                        "$set": {
                            "reminder.last_sent_date": as_iso(today_local),
                            "updated_at": utcnow(),
                        }
                    },
                )

    async def _send_reminder(
        self,
        user_id: int,
        habit: HabitDocument,
        on_date: date,
    ) -> None:
        emoji = habit.get("emoji", "✅")
        name = habit.get("name", "Привычка")
        text = (
            f"{emoji} *Напоминание по привычке*\n"
            f"Сегодня {format_display(on_date)} — самое время выполнить «{name}»!"
        )
        await self.bot.send_message(
            user_id,
            text,
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        log.info("Reminder sent for user %s habit %s", user_id, habit.get("_id"))
