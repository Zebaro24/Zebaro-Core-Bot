import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.base_service import BaseService

logger = logging.getLogger("services.vpn")

# Every few minutes: traffic totals, "connected for the first time", "access ends tomorrow".
WATCH_JOB_ID = "vpn_watch"
WATCH_MINUTES = 5
# Friday evening, next to the job digest.
WEEKLY_JOB_ID = "vpn_weekly"

_JOB_IDS = [WATCH_JOB_ID, WEEKLY_JOB_ID]


class VpnService(BaseService):
    """The bot's side of the WireGuard server: its jobs pause with it, /vpn refuses while off.

    Switching it off does not stop WireGuard — the container keeps serving the people in it.
    """

    name = "vpn"
    display_name = "VPN в боте (/vpn, уведомления)"
    infra_deps = ["mongodb"]

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
