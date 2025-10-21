from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler


class Scheduler(AsyncIOScheduler):
    def __init__(self):
        super().__init__(executors={"default": AsyncIOExecutor()})


scheduler = Scheduler()


def start_scheduler():
    scheduler.start()
