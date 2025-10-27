import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


load_dotenv()


@dataclass(slots=True)
class Settings:
    """Container for environment-driven configuration with sane defaults."""

    bot_token: str = field(default_factory=lambda: _require("BOT_TOKEN"))
    mongo_uri: str = field(default_factory=lambda: _require("MONGO_URI"))
    mongo_db: str = field(default_factory=lambda: os.getenv("MONGO_DB", "habit_tracker_bot"))
    webhook_base: str = field(default_factory=lambda: _require("WEBHOOK_BASE"))
    cron_secret: str | None = field(default_factory=lambda: os.getenv("CRON_SECRET"))
    timezone: str = field(default_factory=lambda: os.getenv("TZ", "Asia/Almaty"))
    reminder_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("REMINDER_INTERVAL_SECONDS", "60"))
    )
    default_reminder_time: str = field(default_factory=lambda: os.getenv("DEFAULT_REMINDER_TIME", "21:00"))

    animation_urls: Tuple[str, ...] = (
        "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
        "https://media.giphy.com/media/111ebonMs90YLu/giphy.gif",
        "https://media.giphy.com/media/xT9IgG50Fb7Mi0prBC/giphy.gif",
    )

    @property
    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"{key} environment variable is required")
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

