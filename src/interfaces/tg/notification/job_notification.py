import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
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

# How many flood-control waits one vacancy may take before it is given up on.
_SEND_ATTEMPTS = 5

# Webhook updates are now handled concurrently, so nothing else stops a manual search
# from overlapping another one (or the scheduled run) and sending every vacancy twice.
_run_lock = asyncio.Lock()


def is_job_search_running() -> bool:
    return _run_lock.locked()


def _get_reply_markup(job_id: str | None, link: str | None) -> InlineKeyboardMarkup | None:
    if job_id:
        return get_job_action_kb(job_id)
    if link:
        # save_jobs_to_db() не вернул id (БД недоступна) — без этого вакансию было бы
        # невозможно открыть вообще, т.к. в тексте сообщения ссылки больше нет (см. formatters/job.py).
        return get_job_link_kb(link)
    return None


async def _send_job(bot: Bot, text: str, reply_markup: InlineKeyboardMarkup | None) -> bool:
    for _ in range(_SEND_ATTEMPTS):
        try:
            await bot.send_message(
                chat_id=settings.telegram_admin_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            return True
        except TelegramRetryAfter as e:
            # The vacancies are already saved, so a dropped message is never offered again.
            logger.warning("Telegram flood control, waiting %s s", e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramAPIError:
            logger.exception("Failed to send a vacancy, moving on to the next one")
            return False
    logger.error("Gave up on a vacancy after %d flood-control waits", _SEND_ATTEMPTS)
    return False


async def job_notification(bot: Bot) -> int:
    """Search, store and send new vacancies. Returns how many were sent."""
    if _run_lock.locked():
        logger.warning("Job search is already running, skipping this run")
        return 0
    async with _run_lock:
        return await _run_job_notification(bot)


async def _run_job_notification(bot: Bot) -> int:
    logger.info("Starting job notification run")

    job_storage = JobStorage()
    await JobParser(urls, job_storage).parse_urls()

    await job_storage.remove_jobs_already_in_db()
    job_storage.log_jobs()

    if not job_storage.jobs:
        logger.info("No new jobs to send")
        return 0

    JobFilter(job_storage).classify_all()

    ids = await job_storage.save_jobs_to_db()
    # Дедуп идёт после сохранения (не как в плане): так у self.jobs уже есть реальные mongo _id,
    # и сравнение с БД за 14 дней естественно покрывает и дубликаты внутри текущего батча.
    await mark_cross_platform_duplicates(job_storage.jobs, ids)

    sent = 0
    for job, job_id in zip(job_storage.jobs, ids):
        if job.moderation == "rejected_by_filter":
            continue
        if await _send_job(bot, job_to_html(job), _get_reply_markup(job_id, job.link)):
            sent += 1

    logger.info("Job notification complete. Sent %d/%d jobs", sent, len(job_storage.jobs))
    return sent
