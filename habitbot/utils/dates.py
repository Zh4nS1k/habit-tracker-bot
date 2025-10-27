from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ..models import HabitDocument, RepeatMode

DATE_RX = re.compile(r"^(\d{2})\.(\d{2})(?:\.(\d{4}))?$")
ISO_FMT = "%Y-%m-%d"
DISPLAY_FMT = "%d.%m.%Y"


def utcnow() -> datetime:
    return datetime.utcnow().replace(tzinfo=None)


def as_iso(day: date) -> str:
    return day.strftime(ISO_FMT)


def parse_iso(value: str) -> date:
    return datetime.strptime(value, ISO_FMT).date()


def format_display(day: date) -> str:
    return day.strftime(DISPLAY_FMT)


def tz_today(tz: ZoneInfo) -> date:
    return datetime.now(tz=tz).date()


def tz_now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz=tz)


def parse_user_date(raw: str, tz: ZoneInfo) -> Optional[date]:
    text = (raw or "").strip().lower()
    if not text:
        return None

    today = tz_today(tz)
    if text in {"сегодня", "today"}:
        return today
    if text in {"завтра", "tomorrow"}:
        return today + timedelta(days=1)
    if text in {"вчера", "yesterday"}:
        return today - timedelta(days=1)

    match = DATE_RX.match(text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3) or today.year)
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        if not match.group(3) and parsed < today:
            try:
                parsed = date(year + 1, month, day)
            except ValueError:
                last_day = calendar.monthrange(year + 1, month)[1]
                parsed = date(year + 1, month, last_day)
        return parsed

    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
        return parsed
    except ValueError:
        return None


def is_due_on(habit: HabitDocument, day: date) -> bool:
    start_str = habit.get("start_date")
    if not start_str:
        return False
    start = parse_iso(start_str)
    if day < start:
        return False
    target_str = habit.get("target_date")
    if target_str and day > parse_iso(target_str):
        return False

    repeat = habit.get("repeat", {})
    mode = RepeatMode(repeat.get("mode", RepeatMode.DAILY))

    if mode is RepeatMode.DAILY:
        return True

    if mode is RepeatMode.INTERVAL:
        interval = max(1, int(repeat.get("interval_days") or 1))
        delta = (day - start).days
        return delta % interval == 0

    weekday = day.weekday()

    if mode is RepeatMode.WEEKLY:
        desired = repeat.get("week_day")
        if desired is None:
            desired = start.weekday()
        return weekday == int(desired)

    if mode is RepeatMode.WEEKDAYS:
        allowed = repeat.get("weekdays") or []
        if not allowed:
            allowed = list(range(7))
        return weekday in allowed

    if mode is RepeatMode.MONTHLY:
        month_day = int(repeat.get("month_day") or start.day)
        last_day = calendar.monthrange(day.year, day.month)[1]
        effective_day = min(month_day, last_day)
        return day.day == effective_day

    return True


def previous_due_date(habit: HabitDocument, from_day: date) -> Optional[date]:
    start_str = habit.get("start_date")
    if not start_str:
        return None
    start = parse_iso(start_str)
    if from_day <= start:
        return None

    repeat = habit.get("repeat", {})
    mode = RepeatMode(repeat.get("mode", RepeatMode.DAILY))

    if mode is RepeatMode.DAILY:
        candidate = from_day - timedelta(days=1)
    elif mode is RepeatMode.INTERVAL:
        interval = max(1, int(repeat.get("interval_days") or 1))
        candidate = from_day - timedelta(days=interval)
    elif mode is RepeatMode.WEEKLY:
        candidate = from_day - timedelta(days=7)
    elif mode is RepeatMode.WEEKDAYS:
        allowed = repeat.get("weekdays") or []
        if not allowed:
            allowed = list(range(7))
        candidate = from_day - timedelta(days=1)
        while candidate >= start:
            if candidate.weekday() in allowed and is_due_on(habit, candidate):
                break
            candidate -= timedelta(days=1)
    elif mode is RepeatMode.MONTHLY:
        month_day = int(repeat.get("month_day") or start.day)
        first_of_month = from_day.replace(day=1)
        previous_month_last = first_of_month - timedelta(days=1)
        last_day_prev = calendar.monthrange(previous_month_last.year, previous_month_last.month)[1]
        effective_day = min(month_day, last_day_prev)
        candidate = previous_month_last.replace(day=effective_day)
    else:
        candidate = from_day - timedelta(days=1)

    if candidate < start:
        return None

    if not is_due_on(habit, candidate):
        if mode in {RepeatMode.DAILY, RepeatMode.INTERVAL, RepeatMode.WEEKLY}:
            return previous_due_date(habit, candidate)
        return None

    return candidate

