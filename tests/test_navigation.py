from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from habitbot.handlers.habits import _habit_details_text, _is_cancel
from habitbot.keyboards import habit_edit_keyboard, navigation_keyboard, with_navigation


def test_navigation_keyboard_contains_back_and_cancel():
    markup = navigation_keyboard(cancel_cb="cancel_cb", back_cb="back_cb")
    assert len(markup.inline_keyboard) == 1
    row = markup.inline_keyboard[0]
    assert row[0].text == "⬅️ Назад"
    assert row[0].callback_data == "back_cb"
    assert row[1].text == "✖️ Отмена"
    assert row[1].callback_data == "cancel_cb"


def test_with_navigation_appends_buttons():
    base = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="A", callback_data="a")]])
    markup = with_navigation(base, cancel_cb="cancel", back_cb="back")
    assert len(markup.inline_keyboard) == 2
    nav_row = markup.inline_keyboard[-1]
    assert [btn.text for btn in nav_row] == ["⬅️ Назад", "✖️ Отмена"]
    assert nav_row[0].callback_data == "back"
    assert nav_row[1].callback_data == "cancel"


def test_habit_edit_keyboard_has_expected_callbacks():
    markup = habit_edit_keyboard("habit123")
    callbacks = {btn.callback_data for row in markup.inline_keyboard for btn in row}
    assert f"habit:edit:name:habit123" in callbacks
    assert f"habit:edit:emoji:habit123" in callbacks
    assert f"habit:edit:description:habit123" in callbacks
    assert f"habit:view:habit123" in callbacks


def test_is_cancel_matches_keywords():
    assert _is_cancel("Отмена")
    assert _is_cancel("стоп")
    assert _is_cancel("CANCEL")
    assert not _is_cancel("продолжить")


def test_habit_details_text_fallbacks():
    habit = {
        "_id": "1",
        "name": "Вода",
        "emoji": "💧",
        "description": "",
        "start_date": "2024-01-01",
        "repeat": {"mode": "daily"},
        "reminder": {"enabled": False},
        "current_streak": 0,
        "best_streak": 5,
    }
    text = _habit_details_text(habit)
    assert "💧 *Вода*" in text
    assert "*Старт:* 01.01.2024" in text
    assert "*Расписание:* Каждый день" in text
    assert "*Напоминание:* Выключено" in text
    assert "—" in text
