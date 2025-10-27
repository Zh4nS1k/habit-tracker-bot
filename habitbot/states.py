from aiogram.fsm.state import State, StatesGroup


class CreateHabit(StatesGroup):
    waiting_name = State()
    waiting_emoji = State()
    waiting_description = State()
    waiting_start = State()
    waiting_target = State()
    waiting_repeat_mode = State()
    waiting_repeat_payload = State()
    waiting_reminder_toggle = State()
    waiting_reminder_time = State()
    waiting_confirmation = State()


class ReminderTimeUpdate(StatesGroup):
    waiting_time = State()


class TimezoneUpdate(StatesGroup):
    waiting_timezone = State()


class SettingsReminder(StatesGroup):
    waiting_time = State()
