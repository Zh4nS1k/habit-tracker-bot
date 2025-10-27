from __future__ import annotations

from datetime import date
from typing import Iterable, List, Optional, Tuple

from bson import ObjectId

from ..config import get_settings
from ..db import col_habits, col_records, col_users
from ..models import HabitDocument, ReminderConfig, RepeatMode, UserSettingsDocument
from ..utils.dates import as_iso, previous_due_date, utcnow

settings = get_settings()


async def ensure_user_settings(user_id: int) -> UserSettingsDocument:
    existing = await col_users.find_one({"user_id": user_id})
    if existing:
        return existing  # type: ignore[return-value]

    now = utcnow()
    doc: UserSettingsDocument = {
        "user_id": user_id,
        "timezone": settings.timezone,
        "default_reminder_time": settings.default_reminder_time,
        "created_at": now,
        "updated_at": now,
    }
    await col_users.insert_one(doc)
    return doc


async def get_user_settings(user_id: int) -> UserSettingsDocument:
    doc = await col_users.find_one({"user_id": user_id})
    if doc:
        return doc  # type: ignore[return-value]
    return await ensure_user_settings(user_id)


async def update_user_settings(
    user_id: int,
    *,
    timezone: Optional[str] = None,
    default_reminder_time: Optional[str] = None,
) -> UserSettingsDocument:
    updates = {}
    if timezone:
        updates["timezone"] = timezone
    if default_reminder_time:
        updates["default_reminder_time"] = default_reminder_time
    if not updates:
        doc = await ensure_user_settings(user_id)
        return doc

    updates["updated_at"] = utcnow()
    await col_users.update_one({"user_id": user_id}, {"$set": updates}, upsert=True)
    doc = await col_users.find_one({"user_id": user_id})
    if doc:
        return doc  # type: ignore[return-value]
    raise RuntimeError("Failed to update user settings")


async def list_active_habits(user_id: int) -> List[HabitDocument]:
    cursor = col_habits.find({"user_id": user_id, "archived": {"$ne": True}}).sort("created_at", 1)
    return [habit async for habit in cursor]


async def list_due_habits(user_id: int, *, on_date: date) -> List[HabitDocument]:
    habits = await list_active_habits(user_id)
    from ..utils.dates import is_due_on

    due = [habit for habit in habits if is_due_on(habit, on_date)]
    due.sort(key=lambda h: (h.get("reminder", {}).get("time") or settings.default_reminder_time, h["name"]))
    return due


async def create_habit(
    user_id: int,
    *,
    name: str,
    emoji: str,
    description: str,
    start_date: date,
    target_date: Optional[date],
    repeat: dict,
    reminder_enabled: bool,
    reminder_time: Optional[str],
) -> HabitDocument:
    now = utcnow()
    repeat_mode = RepeatMode(repeat.get("mode", RepeatMode.DAILY))

    reminder: ReminderConfig = {
        "enabled": bool(reminder_enabled),
        "time": reminder_time or settings.default_reminder_time,
        "last_sent_date": None,
    }

    doc: HabitDocument = {
        "user_id": user_id,
        "name": name,
        "emoji": emoji,
        "description": description,
        "start_date": as_iso(start_date),
        "target_date": as_iso(target_date) if target_date else None,
        "archived": False,
        "repeat": {
            "mode": repeat_mode,
            **{k: v for k, v in repeat.items() if k != "mode"},
        },
        "reminder": reminder,
        "created_at": now,
        "updated_at": now,
        "current_streak": 0,
        "best_streak": 0,
        "last_completed_on": None,
    }

    result = await col_habits.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_habit(habit_id: str | ObjectId, user_id: Optional[int] = None) -> Optional[HabitDocument]:
    oid = ObjectId(habit_id) if not isinstance(habit_id, ObjectId) else habit_id
    query = {"_id": oid}
    if user_id is not None:
        query["user_id"] = user_id
    habit = await col_habits.find_one(query)
    return habit  # type: ignore[return-value]


async def archive_habit(habit_id: str | ObjectId, user_id: int) -> bool:
    oid = ObjectId(habit_id) if not isinstance(habit_id, ObjectId) else habit_id
    res = await col_habits.update_one(
        {"_id": oid, "user_id": user_id},
        {"$set": {"archived": True, "updated_at": utcnow()}},
    )
    return res.modified_count > 0


async def update_reminder(
    habit_id: str | ObjectId,
    user_id: int,
    *,
    enabled: Optional[bool] = None,
    reminder_time: Optional[str] = None,
) -> Optional[HabitDocument]:
    habit = await get_habit(habit_id, user_id)
    if not habit:
        return None
    reminder = habit.get("reminder", {})
    if enabled is not None:
        reminder["enabled"] = enabled
    if reminder_time:
        reminder["time"] = reminder_time
    reminder["last_sent_date"] = None
    await col_habits.update_one(
        {"_id": habit["_id"]},
        {"$set": {"reminder": reminder, "updated_at": utcnow()}},
    )
    habit["reminder"] = reminder
    return habit


async def mark_completed(
    habit_id: str | ObjectId,
    user_id: int,
    *,
    on_date: date,
) -> Tuple[bool, Optional[HabitDocument]]:
    habit = await get_habit(habit_id, user_id)
    if not habit or habit.get("archived"):
        return False, None

    oid = habit["_id"]
    day_key = as_iso(on_date)
    now = utcnow()

    result = await col_records.update_one(
        {"habit_id": oid, "user_id": user_id, "date": day_key},
        {"$setOnInsert": {"status": "done", "created_at": now}},
        upsert=True,
    )

    inserted = result.upserted_id is not None
    if not inserted:
        return False, habit

    streak = await calculate_streak(habit, on_date)
    best = max(int(habit.get("best_streak") or 0), streak)
    await col_habits.update_one(
        {"_id": oid},
        {
            "$set": {
                "current_streak": streak,
                "best_streak": best,
                "last_completed_on": day_key,
                "updated_at": now,
                "reminder.last_sent_date": day_key,
            }
        },
    )

    habit["current_streak"] = streak
    habit["best_streak"] = best
    habit["last_completed_on"] = day_key
    habit.setdefault("reminder", {})["last_sent_date"] = day_key
    return True, habit


async def calculate_streak(habit: HabitDocument, reference_day: date) -> int:
    habit_id = habit["_id"]
    cursor = col_records.find(
        {"habit_id": habit_id, "date": {"$lte": as_iso(reference_day)}},
        projection={"date": True, "_id": False},
    ).sort("date", -1)

    dates: List[str] = []
    async for doc in cursor:
        dates.append(doc["date"])
        if len(dates) > 380:
            break

    date_set = set(dates)

    streak = 0
    pointer = reference_day

    from ..utils.dates import is_due_on

    while True:
        if as_iso(pointer) not in date_set:
            break
        if not is_due_on(habit, pointer):
            break
        streak += 1
        prev = previous_due_date(habit, pointer)
        if prev is None:
            break
        pointer = prev

    return streak


async def completions_for_period(
    user_id: int,
    start: date,
    end: date,
) -> List[dict]:
    cursor = col_records.find(
        {
            "user_id": user_id,
            "date": {"$gte": as_iso(start), "$lte": as_iso(end)},
        }
    )
    items = [doc async for doc in cursor]
    return items


async def completions_for_habit(
    habit_id: ObjectId,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> List[str]:
    query: dict = {"habit_id": habit_id}
    if start or end:
        date_query = {}
        if start:
            date_query["$gte"] = as_iso(start)
        if end:
            date_query["$lte"] = as_iso(end)
        query["date"] = date_query
    cursor = col_records.find(query, projection={"date": True, "_id": False}).sort("date", 1)
    return [doc["date"] async for doc in cursor]


async def habits_with_due_reminders(on_date: date) -> Iterable[HabitDocument]:
    habits = col_habits.find({"archived": {"$ne": True}, "reminder.enabled": True})
    from ..utils.dates import is_due_on

    async for habit in habits:
        if is_due_on(habit, on_date):
            yield habit  # type: ignore[misc]


async def reset_reminder_flag(habit_id: ObjectId) -> None:
    await col_habits.update_one(
        {"_id": habit_id},
        {"$set": {"reminder.last_sent_date": None}},
    )


async def has_completion_on_date(
    habit_id: ObjectId,
    user_id: int,
    on_date: date,
) -> bool:
    doc = await col_records.find_one(
        {"habit_id": habit_id, "user_id": user_id, "date": as_iso(on_date)},
        projection={"_id": True},
    )
    return bool(doc)


async def update_habit_fields(
    habit_id: str | ObjectId,
    user_id: int,
    **fields,
) -> bool:
    if not fields:
        return False
    oid = ObjectId(habit_id) if not isinstance(habit_id, ObjectId) else habit_id
    fields["updated_at"] = utcnow()
    result = await col_habits.update_one(
        {"_id": oid, "user_id": user_id},
        {"$set": fields},
    )
    return result.modified_count > 0


async def delete_habit_permanently(habit_id: str | ObjectId, user_id: int) -> bool:
    oid = ObjectId(habit_id) if not isinstance(habit_id, ObjectId) else habit_id
    await col_records.delete_many({"habit_id": oid, "user_id": user_id})
    result = await col_habits.delete_one({"_id": oid, "user_id": user_id})
    return result.deleted_count > 0
