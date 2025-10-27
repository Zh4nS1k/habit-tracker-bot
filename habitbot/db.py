from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from .config import get_settings


_settings = get_settings()
_client = AsyncIOMotorClient(_settings.mongo_uri)
database: AsyncIOMotorDatabase = _client[_settings.mongo_db]

col_users = database["users"]
col_habits = database["habits"]
col_records = database["records"]


async def ensure_indexes() -> None:
    await col_users.create_index([("user_id", ASCENDING)], unique=True)

    await col_habits.create_index(
        [("user_id", ASCENDING), ("archived", ASCENDING), ("created_at", DESCENDING)]
    )
    await col_habits.create_index(
        [("reminder.enabled", ASCENDING), ("reminder.time", ASCENDING), ("user_id", ASCENDING)]
    )

    await col_records.create_index([("habit_id", ASCENDING), ("date", ASCENDING)], unique=True)
    await col_records.create_index([("user_id", ASCENDING), ("date", ASCENDING)])


def get_client() -> AsyncIOMotorClient:
    return _client

