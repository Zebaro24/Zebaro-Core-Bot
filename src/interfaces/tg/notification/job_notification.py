import logging

from aiogram import Bot

from src.config import settings
from src.services.job_searcher.container import JobStorage
from src.services.job_searcher.filter import JobFilter
from src.services.job_searcher.formatter import job_to_html
from src.services.job_searcher.parser import JobParser
from src.services.job_searcher.urls import urls

logger = logging.getLogger("tg.notification.job")


async def job_notification(bot: Bot) -> None:
    logger.info("Starting job notification run")

    job_storage = JobStorage()
    parser = JobParser(urls, job_storage)
    await parser.parse_urls()

    job_filter = JobFilter(job_storage)
    job_filter.filter_all()

    await job_storage.remove_jobs_already_in_db()
    job_storage.log_jobs()

    if not job_storage.jobs:
        logger.info("No new jobs to send")
        return

    for job in job_storage.jobs:
        await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=job_to_html(job),
            disable_web_page_preview=True,
        )

    await job_storage.save_jobs_to_db()
    logger.info("Job notification complete. Sent %d jobs", len(job_storage.jobs))
