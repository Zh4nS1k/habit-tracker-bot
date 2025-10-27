from aiogram import Router

from . import create_habit, habits, mark, settings, start, stats


def get_routers() -> list[Router]:
    return [
        start.router,
        create_habit.router,
        mark.router,
        habits.router,
        stats.router,
        settings.router,
    ]

