import asyncio
import logging

from habitbot.bot import bot, dp, reminder_service
from habitbot.db import ensure_indexes


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await ensure_indexes()
    reminder_service.start()
    try:
        await dp.start_polling(bot)
    finally:
        await reminder_service.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

