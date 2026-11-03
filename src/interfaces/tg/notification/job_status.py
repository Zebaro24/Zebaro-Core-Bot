"""Telegram after a status change: edit the vacancy's message, send the change note.

The write (services/job_searcher/status.py) marks the document `tg_sync: pending`; this loop runs
every minute, and right away after a PATCH (`kick_status_sync`). The mark lives in MongoDB, so a
restart loses nothing. One loop is one sender: changes go out one by one, and a 429 is waited out.

- The message is rendered from the document as it is now, not from the event: edits are
  idempotent, and two changes in a row end on the latest one.
- "message is not modified" is success. "message to edit not found" → `gone`: no new vacancy
  message, but the note is still sent (on its own, with the vacancy's link).
- A timeout or a 5xx → tried again later, with a growing pause; a 429 → after `retry_after`.
- The note is sent only for the vacancy's latest event and only when the writer asked (an AI
  change): a later change made by a button needs no note about the earlier one.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InputRichMessage, ReplyParameters
from pymongo.errors import PyMongoError

from src.config import settings
from src.db.client import jobs_collection
from src.interfaces.tg.formatters.job import job_to_html, job_to_rich_html
from src.interfaces.tg.formatters.job_status import job_status_line, status_change_html
from src.interfaces.tg.keyboards.job import get_job_status_kb, get_job_undo_kb
from src.services.job_searcher.container import Job
from src.services.job_searcher.jobs_api import public_status
from src.services.job_searcher.status import LOUD

logger = logging.getLogger("tg.notification.job_status")

SYNC_JOB_ID = "job_status_sync"
SYNC_MINUTES = 1
_BATCH = 20
_ROUNDS = 5  # batches per run; what is left waits for the next minute
_MAX_ATTEMPTS = 8  # timeouts and 5xx before the change is given up on ("failed")
_INLINE_WAIT = 30  # a 429 up to this long is waited out in place, a longer one moves the change on
_RETRY_AFTER_TRIES = 3
DONE, GONE, FAILED = "done", "gone", "failed"


class _FloodWait(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__(seconds)
        self.seconds = seconds


def kick_status_sync() -> None:
    """Run the sync now instead of within a minute (after a PATCH). Never fails the caller."""
    try:
        from src.scheduler import scheduler  # the scheduler reads settings when it is built

        scheduler.modify_job(SYNC_JOB_ID, next_run_time=datetime.now(scheduler.timezone))
    except Exception as e:  # not scheduled (tests, a CLI) or the scheduler is stopped
        logger.debug("Status sync not kicked: %s", e)


def backoff(attempts: int) -> timedelta:
    """30 s, 1 min, 2 min, … up to an hour."""
    return timedelta(seconds=min(30 * 2 ** max(attempts - 1, 0), 3600))


async def sync_job_messages(bot: Bot) -> int:
    """Send what is pending; how many changes were settled (done, gone or failed)."""
    settled, seen = 0, set()
    for _ in range(_ROUNDS):
        try:
            due = {"tg_sync.state": "pending", "tg_sync.next_at": {"$lte": datetime.utcnow()}}
            # Only the ids: each one is read in full right before it is sent (sync_one).
            found = jobs_collection.find(due, {"_id": 1}).sort([("tg_sync.next_at", 1)]).limit(_BATCH)
            docs = [doc async for doc in found if doc["_id"] not in seen]
        except PyMongoError as e:
            logger.warning("Status sync: storage unavailable: %s", e)
            return settled
        if not docs:
            break
        for doc in docs:
            seen.add(doc["_id"])
            try:
                settled += await sync_one(bot, doc["_id"])
            except _FloodWait as e:
                logger.warning("Status sync: Telegram asks to wait %s s; the rest goes later", e.seconds)
                return settled
            except PyMongoError as e:
                logger.warning("Status sync: storage unavailable: %s", e)
                return settled
    return settled


async def sync_one(bot: Bot, object_id: Any) -> int:
    """One change to Telegram; 1 when it is settled, 0 when it is left for later."""
    doc: dict[str, Any] | None = None
    sync: dict[str, Any] = {}
    for _ in range(_RETRY_AFTER_TRIES):
        # Read right before sending, in full: a button may have edited the message meanwhile, and
        # the message is rendered with its description.
        doc = await jobs_collection.find_one({"_id": object_id, "tg_sync.state": "pending"})
        if doc is None:
            return 0
        sync = doc.get("tg_sync") or {}
        event_id = sync.get("event_id")
        try:
            state = await _send(bot, doc, sync)
        except TelegramRetryAfter as e:
            if e.retry_after > _INLINE_WAIT:
                await _later(doc, event_id, timedelta(seconds=e.retry_after), sync.get("attempts") or 0)
                raise _FloodWait(e.retry_after) from None
            await asyncio.sleep(e.retry_after)
            continue
        except (TelegramNetworkError, TelegramServerError) as e:
            logger.info("Status sync of %s: Telegram unreachable (%s)", doc["_id"], e)
            return await _retry_later(doc, sync)
        except TelegramAPIError as e:  # a request Telegram will never take: retrying does not help
            logger.warning("Status sync of %s refused by Telegram: %s", doc["_id"], e)
            await _settle(doc, event_id, FAILED)
            return 1
        except PyMongoError:
            raise
        except Exception:  # an odd document must not hold up every change behind it
            logger.warning("Status sync of %s broke", doc["_id"], exc_info=True)
            return await _retry_later(doc, sync)
        await _settle(doc, event_id, state)
        return 1
    if doc is not None:
        await _later(doc, sync.get("event_id"), timedelta(seconds=_INLINE_WAIT), sync.get("attempts") or 0)
    return 0


async def _retry_later(doc: dict[str, Any], sync: dict[str, Any]) -> int:
    """Try again after a growing pause; after _MAX_ATTEMPTS, give up ("failed")."""
    attempts = (sync.get("attempts") or 0) + 1
    if attempts >= _MAX_ATTEMPTS:
        logger.warning("Status sync of %s failed for good after %d attempts", doc["_id"], attempts)
        await _settle(doc, sync.get("event_id"), FAILED)
        return 1
    await _later(doc, sync.get("event_id"), backoff(attempts), attempts)
    return 0


async def _send(bot: Bot, doc: dict[str, Any], sync: dict[str, Any]) -> str:
    state = DONE
    has_message = bool(doc.get("tg_chat_id") and doc.get("tg_message_id"))
    if has_message and not await _edit(bot, doc):
        state = GONE
    history = doc.get("history") or []
    event = history[-1] if history else None
    if sync.get("notify") and event is not None and event.get("id") == sync.get("event_id"):
        reply_to = doc["tg_message_id"] if has_message and state == DONE else None
        await _notify(bot, doc, event, reply_to)
    return state


async def _edit(bot: Bot, doc: dict[str, Any]) -> bool:
    """Edit the vacancy's message to its current status; False when the message is gone."""
    job_id = str(doc["_id"])
    line = job_status_line(doc)
    markup = get_job_status_kb(job_id, public_status(doc), doc.get("copies"))
    job = Job.from_doc(doc)
    try:
        if doc.get("tg_message_kind") == "plain":
            text = f"{job_to_html(job)}\n\n{line}" if line else job_to_html(job)
            await bot.edit_message_text(
                chat_id=doc["tg_chat_id"], message_id=doc["tg_message_id"], text=text,
                reply_markup=markup, disable_web_page_preview=True,
            )  # fmt: skip
        else:
            await bot.edit_message_text(
                chat_id=doc["tg_chat_id"], message_id=doc["tg_message_id"],
                rich_message=InputRichMessage(html=job_to_rich_html(job, status=line)), reply_markup=markup,
            )  # fmt: skip
    except TelegramBadRequest as e:
        text = str(e).lower()
        if "not modified" in text:
            return True
        if "message to edit not found" in text or "message can't be edited" in text:
            logger.info("Status sync: the message of %s is gone (%s)", job_id, e)
            return False
        raise
    return True


async def _notify(bot: Bot, doc: dict[str, Any], event: dict[str, Any], reply_to: int | None) -> None:
    """The note with "↩️ Отменить": a reply to the vacancy's message, or on its own without one."""
    await bot.send_message(
        chat_id=doc.get("tg_chat_id") or settings.telegram_admin_id,
        text=status_change_html(doc, event),
        reply_markup=get_job_undo_kb(str(doc["_id"]), event["id"], with_link=reply_to is None),
        reply_parameters=ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None,
        disable_notification=event.get("to") not in LOUD,
        disable_web_page_preview=True,
    )


async def _settle(doc: dict[str, Any], event_id: str | None, state: str) -> None:
    if state != FAILED:
        logger.info("Status sync of %s: %s (event %s)", doc["_id"], state, event_id)
    # Only the change this run sent: a newer PATCH meanwhile keeps its own "pending".
    await _update(doc, event_id, {"tg_sync.state": state, "tg_sync.settled_at": datetime.utcnow()})


async def _later(doc: dict[str, Any], event_id: str | None, pause: timedelta, attempts: int) -> None:
    await _update(doc, event_id, {"tg_sync.next_at": datetime.utcnow() + pause, "tg_sync.attempts": attempts})


async def _update(doc: dict[str, Any], event_id: str | None, change: dict[str, Any]) -> None:
    try:
        await jobs_collection.update_one({"_id": doc["_id"], "tg_sync.event_id": event_id}, {"$set": change})
    except PyMongoError as e:  # sent already; at worst it is sent once more next minute
        logger.warning("Status sync: could not store the state of %s: %s", doc["_id"], e)
