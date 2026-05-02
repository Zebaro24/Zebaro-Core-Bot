import logging

from pymongo import AsyncMongoClient

from src.config import settings

logger = logging.getLogger("db.client")

client: AsyncMongoClient = AsyncMongoClient(settings.mongo_uri)
db = client.get_database()

jobs_collection = db["jobs"]
github_notification_collection = db["github_notification"]


async def start_db() -> None:
    try:
        await client.aconnect()
        logger.info("MongoDB connected: %s", settings.mongo_uri)
    except Exception as e:
        logger.warning("MongoDB connection failed, running without DB: %s", e)
