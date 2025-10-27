from datetime import date

from habitbot.models import HabitDocument
from habitbot.utils.dates import as_iso, is_due_on, previous_due_date


def build_habit(**kwargs) -> HabitDocument:
    base: HabitDocument = {
        "user_id": 1,
        "name": "Test",
        "emoji": "🔥",
        "description": "",
        "start_date": as_iso(date(2024, 1, 1)),
        "archived": False,
        "repeat": {"mode": "daily"},
        "reminder": {"enabled": False, "time": "21:00", "last_sent_date": None},
        "created_at": None,
        "updated_at": None,
        "current_streak": 0,
        "best_streak": 0,
        "last_completed_on": None,
    }
    base.update(kwargs)
    return base


def test_is_due_daily():
    habit = build_habit()
    assert is_due_on(habit, date(2024, 1, 1))
    assert is_due_on(habit, date(2024, 1, 5))


def test_is_due_weekdays():
    habit = build_habit(repeat={"mode": "weekdays", "weekdays": [0, 2, 4]})
    assert is_due_on(habit, date(2024, 1, 1))  # Monday
    assert not is_due_on(habit, date(2024, 1, 2))  # Tuesday
    assert is_due_on(habit, date(2024, 1, 3))  # Wednesday


def test_is_due_interval():
    habit = build_habit(repeat={"mode": "interval", "interval_days": 3})
    assert is_due_on(habit, date(2024, 1, 1))
    assert not is_due_on(habit, date(2024, 1, 2))
    assert is_due_on(habit, date(2024, 1, 4))


def test_is_due_weekly():
    habit = build_habit(repeat={"mode": "weekly", "week_day": 2})
    assert is_due_on(habit, date(2024, 1, 3))  # Wednesday
    assert not is_due_on(habit, date(2024, 1, 4))


def test_is_due_monthly():
    habit = build_habit(repeat={"mode": "monthly", "month_day": 31})
    assert is_due_on(habit, date(2024, 1, 31))
    # February should clamp to last day
    assert is_due_on(habit, date(2024, 2, 29))


def test_previous_due_date_daily():
    habit = build_habit()
    assert previous_due_date(habit, date(2024, 1, 2)) == date(2024, 1, 1)
    assert previous_due_date(habit, date(2024, 1, 1)) is None


def test_previous_due_date_weekdays():
    habit = build_habit(repeat={"mode": "weekdays", "weekdays": [0, 2, 4]})
    assert previous_due_date(habit, date(2024, 1, 5)) == date(2024, 1, 3)


def test_previous_due_date_interval():
    habit = build_habit(repeat={"mode": "interval", "interval_days": 4})
    assert previous_due_date(habit, date(2024, 1, 9)) == date(2024, 1, 5)


def test_previous_due_date_weekly():
    habit = build_habit(repeat={"mode": "weekly", "week_day": 0})
    assert previous_due_date(habit, date(2024, 1, 15)) == date(2024, 1, 8)


def test_previous_due_date_monthly():
    habit = build_habit(repeat={"mode": "monthly", "month_day": 31})
    assert previous_due_date(habit, date(2024, 3, 31)) == date(2024, 2, 29)
