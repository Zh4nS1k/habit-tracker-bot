from __future__ import annotations

from typing import Iterable, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .models import HabitDocument

EMOJI_CHOICES = ("🔥", "🌱", "💧", "📚", "💤", "🏃", "🧘", "🍎", "🎯", "✨")


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Добавить привычку"),
                KeyboardButton(text="✅ Отметить сегодня"),
            ],
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="📅 Мои привычки"),
            ],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def habits_inline_keyboard(habits: Iterable[HabitDocument], action: str) -> InlineKeyboardMarkup:
    rows = []
    for habit in habits:
        text = f"{habit.get('emoji', '✅')} {habit.get('name', 'Без названия')}"
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f"habit:{action}:{habit['_id']}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="common:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def emoji_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for emoji in EMOJI_CHOICES:
        row.append(InlineKeyboardButton(text=emoji, callback_data=f"create:emoji:{emoji}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🎨 Другое", callback_data="create:emoji:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="create:start:today"),
                InlineKeyboardButton(text="Завтра", callback_data="create:start:tomorrow"),
            ],
            [InlineKeyboardButton(text="📅 Ввести дату", callback_data="create:start:manual")],
        ]
    )


def target_date_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Без срока", callback_data="create:target:none"),
                InlineKeyboardButton(text="📅 Задать дату", callback_data="create:target:manual"),
            ]
        ]
    )


def skip_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data=callback_data)]]
    )


def stats_period_keyboard(selected: str = "day") -> InlineKeyboardMarkup:
    mapping = [
        ("day", "Сегодня"),
        ("week", "Неделя"),
        ("month", "Месяц"),
        ("year", "Год"),
        ("all", "Всё время"),
    ]
    buttons = []
    for key, label in mapping:
        mark = "✅ " if key == selected else ""
        buttons.append(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"stats:period:{key}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def repeat_mode_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Каждый день", callback_data="create:repeat:daily"),
            InlineKeyboardButton(text="По будням", callback_data="create:repeat:weekdays"),
        ],
        [
            InlineKeyboardButton(text="Раз в N дней", callback_data="create:repeat:interval"),
            InlineKeyboardButton(text="Раз в неделю", callback_data="create:repeat:weekly"),
        ],
        [InlineKeyboardButton(text="Раз в месяц", callback_data="create:repeat:monthly")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def weekdays_keyboard(selected: Sequence[int]) -> InlineKeyboardMarkup:
    days = [
        ("Пн", 0),
        ("Вт", 1),
        ("Ср", 2),
        ("Чт", 3),
        ("Пт", 4),
        ("Сб", 5),
        ("Вс", 6),
    ]
    row = []
    rows = []
    for title, value in days:
        mark = "✅ " if value in selected else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{title}",
                callback_data=f"create:weekday:{value}",
            )
        )
    rows.append(row[:4])
    rows.append(row[4:])
    rows.append([InlineKeyboardButton(text="Готово", callback_data="create:weekday:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить", callback_data="create:confirm:yes"),
                InlineKeyboardButton(text="🔄 Изменить", callback_data="create:confirm:no"),
            ]
        ]
    )


def reminder_toggle_keyboard(enabled: bool, habit_id: str) -> InlineKeyboardMarkup:
    label = "🔕 Выключить" if enabled else "🔔 Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label, callback_data=f"habit:reminder:toggle:{habit_id}"),
                InlineKeyboardButton(text="⏰ Время", callback_data=f"habit:reminder:time:{habit_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"habit:view:{habit_id}")],
        ]
    )


def habit_details_keyboard(habit: HabitDocument) -> InlineKeyboardMarkup:
    habit_id = str(habit["_id"])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отметить", callback_data=f"habit:done:{habit_id}"),
                InlineKeyboardButton(text="🔔 Напоминание", callback_data=f"habit:reminder:menu:{habit_id}"),
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data=f"habit:stats:{habit_id}"),
                InlineKeyboardButton(text="🗑 Архив", callback_data=f"habit:archive:{habit_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="common:back_habits")],
        ]
    )


def reminder_menu_keyboard(habit: HabitDocument) -> InlineKeyboardMarkup:
    habit_id = str(habit["_id"])
    reminder_enabled = habit.get("reminder", {}).get("enabled", False)
    label = "🔕 Выключить" if reminder_enabled else "🔔 Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"habit:reminder:toggle:{habit_id}")],
            [InlineKeyboardButton(text="⏰ Изменить время", callback_data=f"habit:reminder:time:{habit_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"habit:view:{habit_id}")],
        ]
    )


def reminder_initial_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔔 Включить", callback_data="create:reminder:on"),
                InlineKeyboardButton(text="🔕 Без напоминаний", callback_data="create:reminder:off"),
            ]
        ]
    )


def reminder_time_entry_keyboard(default_time: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🕘 Использовать {default_time}",
                    callback_data="create:reminder:default",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="create:reminder:cancel",
                )
            ],
        ]
    )
