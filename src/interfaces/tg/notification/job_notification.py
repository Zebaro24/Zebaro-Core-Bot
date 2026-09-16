import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from src.config import settings
from src.interfaces.tg.formatters.job import job_to_html
from src.interfaces.tg.keyboards.job import get_job_action_kb, get_job_link_kb
from src.services.job_searcher.container import JobStorage
from src.services.job_searcher.dedup import mark_cross_platform_duplicates
from src.services.job_searcher.filter import JobFilter
from src.services.job_searcher.parser import JobParser
from src.services.job_searcher.urls import urls

logger = logging.getLogger("tg.notification.job")


def _get_reply_markup(job_id: str | None, link: str | None) -> InlineKeyboardMarkup | None:
    if job_id:
        return get_job_action_kb(job_id)
    if link:
        # save_jobs_to_db() не вернул id (БД недоступна) — без этого вакансию было бы
        # невозможно открыть вообще, т.к. в тексте сообщения ссылки больше нет (см. formatters/job.py).
        return get_job_link_kb(link)
    return None


async def job_notification(bot: Bot) -> None:
    logger.info("Starting job notification run")

    job_storage = JobStorage()
    await JobParser(urls, job_storage).parse_urls()

    await job_storage.remove_jobs_already_in_db()
    job_storage.log_jobs()

    if not job_storage.jobs:
        logger.info("No new jobs to send")
        return

    JobFilter(job_storage).classify_all()

    ids = await job_storage.save_jobs_to_db()
    # Дедуп идёт после сохранения (не как в плане): так у self.jobs уже есть реальные mongo _id,
    # и сравнение с БД за 14 дней естественно покрывает и дубликаты внутри текущего батча.
    await mark_cross_platform_duplicates(job_storage.jobs, ids)

    sent = 0
    for job, job_id in zip(job_storage.jobs, ids):
        if job.moderation == "rejected_by_filter":
            continue
        reply_markup = _get_reply_markup(job_id, job.link)
        await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=job_to_html(job),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
        sent += 1

    logger.info("Job notification complete. Sent %d/%d jobs", sent, len(job_storage.jobs))
