from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from bson import ObjectId

from ..db import col_habits, col_records
from ..models import HabitDocument
from ..utils.dates import as_iso, format_display


async def stats_for_period(user_id: int, start: date, end: date) -> Dict:
    pipeline = [
        {
            "$match": {
                "user_id": user_id,
                "date": {"$gte": as_iso(start), "$lte": as_iso(end)},
            }
        },
        {
            "$group": {
                "_id": "$habit_id",
                "count": {"$sum": 1},
            }
        },
    ]
    aggregated = await col_records.aggregate(pipeline).to_list(length=None)
    habit_ids = [entry["_id"] for entry in aggregated]
    habits = await col_habits.find({"_id": {"$in": habit_ids}}).to_list(length=None)
    habit_map = {habit["_id"]: habit for habit in habits}

    per_habit = []
    for entry in aggregated:
        habit = habit_map.get(entry["_id"])
        if habit:
            per_habit.append(
                {
                    "habit_id": entry["_id"],
                    "habit": habit,
                    "count": entry["count"],
                }
            )

    day_pipeline = [
        {
            "$match": {
                "user_id": user_id,
                "date": {"$gte": as_iso(start), "$lte": as_iso(end)},
            }
        },
        {
            "$group": {"_id": "$date", "count": {"$sum": 1}},
        },
        {"$sort": {"count": -1}},
        {"$limit": 1},
    ]
    best_day = await col_records.aggregate(day_pipeline).to_list(length=None)
    best_day_entry = best_day[0] if best_day else None

    total_completed = sum(item["count"] for item in per_habit)
    return {
        "user_id": user_id,
        "start": start,
        "end": end,
        "per_habit": per_habit,
        "total_completed": total_completed,
        "best_day": best_day_entry,
    }


async def daily_completion_map(user_id: int, start: date, end: date) -> Dict[str, List[ObjectId]]:
    pipeline = [
        {
            "$match": {
                "user_id": user_id,
                "date": {"$gte": as_iso(start), "$lte": as_iso(end)},
            }
        },
        {"$group": {"_id": {"date": "$date", "habit_id": "$habit_id"}}},
        {
            "$group": {
                "_id": "$_id.date",
                "habit_ids": {"$push": "$_id.habit_id"},
            }
        },
    ]
    rows = await col_records.aggregate(pipeline).to_list(length=None)
    return {row["_id"]: row["habit_ids"] for row in rows}


def describe_period(start: date, end: date) -> str:
    if start == end:
        return format_display(start)
    return f"{format_display(start)} — {format_display(end)}"


def resolve_period(period: str, today: date) -> tuple[date, date]:
    if period == "day":
        return today, today
    if period == "week":
        start = today - timedelta(days=6)
        return start, today
    if period == "month":
        start = today.replace(day=1)
        return start, today
    if period == "year":
        start = today.replace(month=1, day=1)
        return start, today
    if period == "all":
        far_past = today - timedelta(days=5 * 365)
        return far_past, today
    raise ValueError(f"Unknown period: {period}")

