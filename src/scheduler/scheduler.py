import logging

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings

logger = logging.getLogger("scheduler")


class Scheduler(AsyncIOScheduler):
    def __init__(self) -> None:
        super().__init__(executors={"default": AsyncIOExecutor()}, timezone=settings.tz)


scheduler = Scheduler()


def start_scheduler() -> None:
    scheduler.start()
    logger.info("Scheduler started (timezone: %s)", scheduler.timezone)
