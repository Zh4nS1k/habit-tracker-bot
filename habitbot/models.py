from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, TypedDict

from bson import ObjectId


class RepeatMode(str, Enum):
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    INTERVAL = "interval"


class RepeatConfig(TypedDict, total=False):
    mode: RepeatMode
    weekdays: List[int]
    interval_days: int
    week_day: int
    month_day: int


class ReminderConfig(TypedDict, total=False):
    enabled: bool
    time: str
    last_sent_date: Optional[str]


class HabitDocument(TypedDict, total=False):
    _id: ObjectId
    user_id: int
    name: str
    emoji: str
    description: str
    start_date: str
    target_date: Optional[str]
    archived: bool
    repeat: RepeatConfig
    reminder: ReminderConfig
    created_at: datetime
    updated_at: datetime
    current_streak: int
    best_streak: int
    last_completed_on: Optional[str]


class RecordDocument(TypedDict, total=False):
    _id: ObjectId
    habit_id: ObjectId
    user_id: int
    date: str
    status: str
    created_at: datetime


class UserSettingsDocument(TypedDict, total=False):
    _id: ObjectId
    user_id: int
    timezone: str
    default_reminder_time: str
    created_at: datetime
    updated_at: datetime

