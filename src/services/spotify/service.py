import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.base_service import BaseService

logger = logging.getLogger("services.spotify")

# Daily statement poll — the webhook's safety net, not a feed: two statement requests a day.
# Before the morning reminders, so they work from fresh numbers; "Обновить" polls on demand.
POLL_JOB_ID = "spotify_poll"
POLL_HOUR = 9
POLL_MINUTE = 40
# Reminders: before the charge (three days ahead, the day before) and the follow-up to debtors.
MORNING_JOB_ID = "spotify_morning"
MORNING_HOUR = 10
EVENING_JOB_ID = "spotify_evening"
EVENING_HOUR = 18

_JOB_IDS = [POLL_JOB_ID, MORNING_JOB_ID, EVENING_JOB_ID]


class SpotifyService(BaseService):
    """The family plan's money: its jobs pause with it, /spotify and the webhook refuse while off.

    Off loses nothing: the poll's cursor stays where it was and catches up when switched back on.
    """

    name = "spotify"
    display_name = "Spotify Family (банка, напоминания)"
    infra_deps: list[str] = []

    def __init__(self, scheduler: AsyncIOScheduler) -> None:
        self._scheduler = scheduler

    async def on_enable(self) -> None:
        for job_id in _JOB_IDS:
            if job := self._scheduler.get_job(job_id):
                job.resume()
                logger.info("Resumed scheduler job: %s", job_id)

    async def on_disable(self) -> None:
        for job_id in _JOB_IDS:
            if job := self._scheduler.get_job(job_id):
                job.pause()
                logger.info("Paused scheduler job: %s", job_id)
