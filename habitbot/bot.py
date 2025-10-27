from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from .config import get_settings
from .handlers import get_routers
from .services.reminders import ReminderService


settings = get_settings()
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode="HTML"),
)
dp = Dispatcher()

for router in get_routers():
    dp.include_router(router)

reminder_service = ReminderService(bot)

