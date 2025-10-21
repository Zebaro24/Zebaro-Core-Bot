from pymongo import AsyncMongoClient

from app.config import settings

client = AsyncMongoClient(settings.mongo_uri)
db = client.get_database()

jobs_collection = db["jobs"]
github_notification_collection = db["github_notification"]


async def start_db():
    await client.aconnect()
