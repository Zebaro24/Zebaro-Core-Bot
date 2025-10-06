import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor


class Scheduler(AsyncIOScheduler):
    def __init__(self):
        super().__init__(executors={"default": AsyncIOExecutor()})


scheduler = Scheduler()


async def start_scheduler():
    scheduler.start()
    while True:
        await asyncio.sleep(3600)
