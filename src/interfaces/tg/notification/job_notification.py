import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InputRichMessage

from src.config import settings
from src.interfaces.tg.formatters.job import job_to_html, job_to_rich_html
from src.interfaces.tg.keyboards.job import get_job_action_kb, get_job_link_kb
from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.dedup import DUPLICATE, group_duplicates
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


def _get_reply_markup(job: Job, job_id: str | None) -> InlineKeyboardMarkup | None:
    if job_id:
        return get_job_action_kb(job_id, job.platform_name, job.copies)
    if job.link:
        # save_jobs_to_db() did not return an id (the DB is down): without the raw link the
        # vacancy could not be opened at all — the message text carries no link.
        return get_job_link_kb(job.link)
    return None


async def _deliver(bot: Bot, job: Job, reply_markup: InlineKeyboardMarkup | None) -> None:
    # Only "your stack" rings; partial matches arrive silently and wait to be scrolled.
    silent = job.moderation != "sent"
    try:
        await bot.send_rich_message(
            chat_id=settings.telegram_admin_id,
            # Entity detection stays on: an e-mail or a form link in the description is clickable.
            rich_message=InputRichMessage(html=job_to_rich_html(job)),
            reply_markup=reply_markup,
            disable_notification=silent,
        )
    except TelegramBadRequest:
        logger.warning("Telegram refused the rich message for %s, sending the plain version", job, exc_info=True)
        await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=job_to_html(job),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=silent,
        )


async def _send_job(bot: Bot, job: Job, reply_markup: InlineKeyboardMarkup | None) -> bool:
    for _ in range(_SEND_ATTEMPTS):
        try:
            await _deliver(bot, job, reply_markup)
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
    parser = JobParser(urls, job_storage)
    await parser.parse_urls()

    await job_storage.remove_jobs_already_in_db()
    job_storage.log_jobs()

    if not job_storage.jobs:
        logger.info("No new jobs to send")
        return 0

    job_filter = JobFilter(job_storage)
    # Title first: senior, lead and non-developer roles never cost a page load.
    worth_opening = job_filter.prefilter_all()
    await parser.fetch_descriptions(worth_opening)
    job_filter.classify_all()  # also orders the batch: your stack first, best score first

    ids = await job_storage.save_jobs_to_db()
    # Grouping runs after saving: the copies need real Mongo ids for their link buttons.
    await group_duplicates(job_storage.jobs, ids)

    sent = 0
    for job, job_id in zip(job_storage.jobs, ids):
        if job.moderation == "rejected_by_filter" or job.user_status == DUPLICATE:
            continue
        if await _send_job(bot, job, _get_reply_markup(job, job_id)):
            sent += 1

    logger.info("Job notification complete. Sent %d/%d jobs", sent, len(job_storage.jobs))
    return sent
