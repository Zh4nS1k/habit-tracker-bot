from __future__ import annotations

from typing import Dict
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..keyboards import main_menu_keyboard, stats_period_keyboard
from ..services.habits import get_user_settings
from ..services.stats import describe_period, resolve_period, stats_for_period
from ..utils.dates import format_display, parse_iso, tz_today


router = Router(name="stats")
settings = get_settings()


async def _user_zoneinfo(user_id: int) -> ZoneInfo:
    settings_doc = await get_user_settings(user_id)
    tz_name = settings_doc.get("timezone", settings.timezone)
    return ZoneInfo(tz_name)


def _render_stats(summary: Dict) -> str:
    period = describe_period(summary["start"], summary["end"])
    lines = [f"*Статистика за {period}*"]
    if not summary["per_habit"]:
        lines.append("Пока нет отметок за этот период.")
        return "\n".join(lines)

    lines.append(f"Всего выполнений: {summary['total_completed']}")
    lines.append("")
    for entry in summary["per_habit"]:
        habit = entry["habit"]
        lines.append(
            f"{habit.get('emoji', '✅')} {habit.get('name', 'Привычка')}: {entry['count']} "
            f"(стрик {habit.get('current_streak', 0)}, рекорд {habit.get('best_streak', 0)})"
        )
    best_day = summary.get("best_day")
    if best_day:
        lines.append("")
        lines.append(
            f"Самый продуктивный день: {format_display(parse_iso(best_day['_id']))} — {best_day['count']} привычек"
        )
    return "\n".join(lines)


@router.message(F.text == "📊 Статистика")
async def stats_entry(message: Message) -> None:
    tz = await _user_zoneinfo(message.from_user.id)
    today = tz_today(tz)
    start, end = resolve_period("day", today)
    summary = await stats_for_period(message.from_user.id, start, end)
    text = _render_stats(summary)
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=stats_period_keyboard("day"),
    )


@router.callback_query(F.data.startswith("stats:period:"))
async def stats_period(callback: CallbackQuery) -> None:
    period = callback.data.split(":", 2)[2]
    tz = await _user_zoneinfo(callback.from_user.id)
    today = tz_today(tz)
    start, end = resolve_period(period, today)
    summary = await stats_for_period(callback.from_user.id, start, end)
    text = _render_stats(summary)
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=stats_period_keyboard(period),
    )
    await callback.answer()
