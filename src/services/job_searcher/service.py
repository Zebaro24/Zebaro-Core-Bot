import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.base_service import BaseService

logger = logging.getLogger("services.job_searcher")

_JOB_IDS = ["job_notification_12", "job_notification_14", "job_notification_16"]


class JobSearcherService(BaseService):
    name = "job_searcher"
    display_name = "Job Searcher"
    infra_deps = ["mongodb", "playwright"]

    def __init__(self, bot: Bot, scheduler: AsyncIOScheduler) -> None:
        self._bot = bot
        self._scheduler = scheduler

    async def on_enable(self) -> None:
        for job_id in _JOB_IDS:
            job = self._scheduler.get_job(job_id)
            if job:
                try:
                    job.resume()
                    logger.info("Resumed scheduler job: %s", job_id)
                except Exception as e:
                    logger.warning("Could not resume job %s: %s", job_id, e)

    async def on_disable(self) -> None:
        for job_id in _JOB_IDS:
            job = self._scheduler.get_job(job_id)
            if job:
                try:
                    job.pause()
                    logger.info("Paused scheduler job: %s", job_id)
                except Exception as e:
                    logger.warning("Could not pause job %s: %s", job_id, e)
