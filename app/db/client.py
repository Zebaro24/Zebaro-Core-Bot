from pymongo import AsyncMongoClient
from app.config import settings

client = AsyncMongoClient(settings.mongo_uri)
db = client.get_database()

jobs_collection = db["jobs"]

async def start_db():
    await client.aconnect()
