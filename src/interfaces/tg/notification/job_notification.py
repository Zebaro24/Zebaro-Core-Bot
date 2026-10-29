import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InputRichMessage, Message

from src.config import settings
from src.interfaces.tg.formatters.job import job_to_html, job_to_rich_html, review_summary_html, review_summary_plain
from src.interfaces.tg.keyboards.job import get_job_action_kb, get_job_link_kb, get_job_summary_kb
from src.services.job_searcher.container import Job, JobStorage, remember_message
from src.services.job_searcher.dedup import DUPLICATE, group_duplicates, muted_companies, reject_muted
from src.services.job_searcher.filter import REJECTED, REVIEW, SENT, TOP, JobFilter
from src.services.job_searcher.parser import JobParser
from src.services.job_searcher.urls import urls

logger = logging.getLogger("tg.notification.job")

# Telegram's 🔥 message effect: a vacancy right on target arrives with it. The plain fallback
# goes without — an unknown effect would be the reason the rich one was refused.
FIRE_EFFECT_ID = "5104841245755180586"

# How many flood-control waits one vacancy may take before it is given up on.
_SEND_ATTEMPTS = 5
# Vacancies per 👀 summary message: two buttons a row keeps the keyboard to ten rows.
SUMMARY_CHUNK = 20

# Webhook updates are now handled concurrently, so nothing else stops a manual search
# from overlapping another one (or the scheduled run) and sending every vacancy twice.
_run_lock = asyncio.Lock()


def is_job_search_running() -> bool:
    return _run_lock.locked()


def _get_reply_markup(job: Job, job_id: str | None) -> InlineKeyboardMarkup | None:
    if job_id:
        return get_job_action_kb(job_id, job.copies)
    if job.link:
        # save_jobs_to_db() did not return an id (the DB is down): without the raw link the
        # vacancy could not be opened at all — the message text carries no link.
        return get_job_link_kb(job.link)
    return None


async def _deliver(bot: Bot, job: Job, reply_markup: InlineKeyboardMarkup | None) -> tuple[Message, str]:
    """Send the vacancy; the message and its kind ("rich" | "plain")."""
    # Only "your stack" rings; partial matches arrive silently and wait to be scrolled.
    silent = job.moderation not in (TOP, SENT)
    try:
        message = await bot.send_rich_message(
            chat_id=settings.telegram_admin_id,
            # Entity detection stays on: an e-mail or a form link in the description is clickable.
            rich_message=InputRichMessage(html=job_to_rich_html(job)),
            reply_markup=reply_markup,
            disable_notification=silent,
            message_effect_id=FIRE_EFFECT_ID if job.moderation == TOP else None,
        )
        return message, "rich"
    except TelegramBadRequest:
        logger.warning("Telegram refused the rich message for %s, sending the plain version", job, exc_info=True)
        message = await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=job_to_html(job),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            disable_notification=silent,
        )
        return message, "plain"


async def _deliver_summary(bot: Bot, jobs: list[Job], ids: list[str], first: int, total: int) -> bool:
    entries = [(n, job.title or "", job_id) for n, (job, job_id) in enumerate(zip(jobs, ids, strict=True), first)]
    markup = get_job_summary_kb(entries)
    try:
        await bot.send_rich_message(
            chat_id=settings.telegram_admin_id,
            rich_message=InputRichMessage(html=review_summary_html(jobs, first, total)),
            reply_markup=markup,
            disable_notification=True,
        )
        return True
    except TelegramBadRequest:
        logger.warning("Telegram refused the rich summary, sending the plain version", exc_info=True)
        await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=review_summary_plain(jobs, first, total),
            reply_markup=markup,
            disable_notification=True,
        )
        return True


async def _send_summary(bot: Bot, pairs: list[tuple[Job, str]]) -> int:
    """The 👀 tier as one message (or a few of SUMMARY_CHUNK). Returns how many vacancies went."""
    sent = 0
    for start in range(0, len(pairs), SUMMARY_CHUNK):
        chunk = pairs[start : start + SUMMARY_CHUNK]
        jobs, ids = [job for job, _ in chunk], [job_id for _, job_id in chunk]
        if await _with_retries(partial(_deliver_summary, bot, jobs, ids, start + 1, len(pairs))):
            sent += len(chunk)
    return sent


async def _send_job(bot: Bot, job: Job, reply_markup: InlineKeyboardMarkup | None, job_id: str | None = None) -> bool:
    sent = await _with_retries(partial(_deliver, bot, job, reply_markup))
    if sent is None:
        return False
    if job_id:
        message, kind = sent
        await remember_message(job_id, message.chat.id, message.message_id, kind)
    return True


_T = TypeVar("_T")


async def _with_retries(deliver: Callable[[], Awaitable[_T]]) -> _T | None:
    """What `deliver` returned, or None when the vacancy was given up on."""
    for _ in range(_SEND_ATTEMPTS):
        try:
            return await deliver()
        except TelegramRetryAfter as e:
            # The vacancies are already saved, so a dropped message is never offered again.
            logger.warning("Telegram flood control, waiting %s s", e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramAPIError:
            logger.exception("Failed to send a vacancy, moving on to the next one")
            return None
    logger.error("Gave up on a vacancy after %d flood-control waits", _SEND_ATTEMPTS)
    return None


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
    if muted := reject_muted(job_storage.jobs, await muted_companies()):
        logger.info("Vacancies of muted companies: %d", muted)

    ids = await job_storage.save_jobs_to_db()
    # Grouping runs after saving: the copies need real Mongo ids for their link buttons.
    await group_duplicates(job_storage.jobs, ids)

    sent = 0
    summary: list[tuple[Job, str]] = []
    for job, job_id in zip(job_storage.jobs, ids, strict=True):
        if job.moderation == REJECTED or job.user_status == DUPLICATE:
            continue
        if job.moderation == REVIEW and job_id:
            summary.append((job, job_id))  # sent together after the ones on target
            continue
        if await _send_job(bot, job, _get_reply_markup(job, job_id), job_id):
            sent += 1
    sent += await _send_summary(bot, summary)

    logger.info("Job notification complete. Sent %d/%d jobs", sent, len(job_storage.jobs))
    return sent
