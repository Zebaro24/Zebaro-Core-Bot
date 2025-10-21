from aiogram import Bot

from app.config import settings
from app.services.job_searcher.job_container import JobStorage
from app.services.job_searcher.job_filter import JobFilter
from app.services.job_searcher.job_parser import JobParser
from app.services.job_searcher.job_to_text import job_to_html
from app.services.job_searcher.job_urls import urls


async def job_notification(bot: Bot):
    job_storage = JobStorage()
    parser = JobParser(urls, job_storage)
    await parser.parse_urls()
    job_filter = JobFilter(job_storage)
    job_filter.filter_all()
    await job_storage.remove_jobs_already_in_db()
    job_storage.print_jobs()

    for job in job_storage.jobs:
        await bot.send_message(chat_id=settings.telegram_admin_id, text=job_to_html(job), disable_web_page_preview=True)

    await job_storage.save_jobs_to_db()
