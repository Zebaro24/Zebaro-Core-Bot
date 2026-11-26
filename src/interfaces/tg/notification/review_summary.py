"""The 👀 tier as one message a day (16.11.2026), edited as the day's runs add to it.

Partial matches are a side list: the owner looks through them and answers only when one catches
the eye. A summary per run piled up a dozen messages a day; now a run edits the day's message
(a new one past SUMMARY_CHUNK vacancies — two buttons a row keep the keyboard to ten rows).

The day's messages live in `meta` as `review_summary:<YYYY-MM-DD>` (the owner's clock). Every
vacancy in them carries `review_day`; a status write marks it `review_stale`, and the status sync
loop re-renders that day — a decided vacancy shows its status mark, its button stays.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InputRichMessage

from src.config import settings
from src.db import sql
from src.interfaces.tg.formatters.job import review_summary_html, review_summary_plain
from src.interfaces.tg.formatters.job_status import status_words
from src.interfaces.tg.keyboards.job import get_job_summary_kb
from src.services.job_searcher import store
from src.services.job_searcher.container import Job
from src.services.job_searcher.jobs_api import public_status
from src.services.job_searcher.models import ReviewSummary

logger = logging.getLogger("tg.notification.review_summary")

SUMMARY_CHUNK = 20
_SEND_ATTEMPTS = 5
_STALE_BATCH = 200
# The search run adds, the sync loop re-renders: one at a time, or a render from older state
# drops the vacancies the run just added.
_lock = asyncio.Lock()


async def _state(day: str) -> dict[str, Any] | None:
    async with sql.session() as s:
        row = await s.get(ReviewSummary, day)
        return {"parts": list(row.parts)} if row is not None else None


def today() -> str:
    return datetime.now().date().isoformat()  # the process's clock is the owner's (TZ)


def place(parts: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    """Append the ids to the day's parts: the last one until it holds SUMMARY_CHUNK, then a new one.
    A vacancy already in the day's summary is not added twice."""
    parts = [{**part, "ids": list(part["ids"])} for part in parts]
    known = {job_id for part in parts for job_id in part["ids"]}
    for job_id in ids:
        if job_id in known:
            continue
        if not parts or len(parts[-1]["ids"]) >= SUMMARY_CHUNK:
            parts.append({"ids": [], "chat_id": None, "message_id": None, "kind": None})
        parts[-1]["ids"].append(job_id)
        known.add(job_id)
    return parts


def mark(doc: dict[str, Any]) -> str | None:
    """The status emoji a decided vacancy gets in the summary; None while it waits."""
    words = status_words(public_status(doc), doc.get("status_reason"))
    return words[0] if words else None


async def add_to_summary(bot: Bot, ids: list[str]) -> int:
    """Put the run's 👀 vacancies into today's summary. Returns how many of them are shown."""
    if not ids:
        return 0
    day = today()
    async with _lock:
        try:
            state = await _state(day) or {}
            known = True
        except sql.UNAVAILABLE as e:
            # Sent as a message of its own and not stored: the day's stored messages stay tracked.
            logger.warning("Review summary: storage unavailable, sending the run's summary apart: %s", e)
            state, known = {}, False
        parts = place(state.get("parts") or [], ids)
        shown = await _render(bot, day, parts, send_new=True)
        if known:
            await _save(day, parts)
    try:
        await store.update_where(store.J.id.in_(ids), {"review_day": day})
    except sql.UNAVAILABLE as e:  # the summary is out; only its later status marks are lost
        logger.warning("Review summary: could not mark the vacancies of %s: %s", day, e)
    return len(set(ids) & shown)


async def refresh_stale_summaries(bot: Bot) -> int:
    """Re-render the days whose vacancies changed status since. Returns how many days."""
    try:
        stale = await store.find(store.J.review_stale.is_(True), limit=_STALE_BATCH, history=False, description=False)
        if not stale:
            return 0
        # Cleared before the render reads the statuses: a write landing meanwhile marks it again.
        await store.update_where(store.J.id.in_([doc["_id"] for doc in stale]), {"review_stale": None})
    except sql.UNAVAILABLE as e:
        logger.warning("Review summary: storage unavailable: %s", e)
        return 0
    days = sorted({doc["review_day"] for doc in stale if doc.get("review_day")})
    async with _lock:  # a run adding to the day at the same time must not be rendered over
        for day in days:
            try:
                state = await _state(day)
            except sql.UNAVAILABLE as e:
                logger.warning("Review summary: storage unavailable: %s", e)
                return 0
            if state and state.get("parts"):
                await _render(bot, day, state["parts"], send_new=False)
    return len(days)


async def _save(day: str, parts: list[dict[str, Any]]) -> None:
    try:
        async with sql.session() as s:
            row = await s.get(ReviewSummary, day, with_for_update=True)
            if row is None:
                s.add(ReviewSummary(day=day, parts=list(parts)))
            else:
                row.parts = list(parts)
            await s.commit()
    except sql.UNAVAILABLE as e:  # tomorrow starts anew anyway; today's next run sends a new message
        logger.warning("Review summary: could not store the messages of %s: %s", day, e)


async def _docs(parts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ids = [job_id for part in parts for job_id in part["ids"]]
    try:
        return {doc["_id"]: doc for doc in await store.find(store.J.id.in_(ids), description=False)}
    except sql.UNAVAILABLE as e:
        logger.warning("Review summary: could not read the vacancies: %s", e)
        return {}


async def _render(bot: Bot, day: str, parts: list[dict[str, Any]], *, send_new: bool) -> set[str]:
    """Edit (or send) every part of the day; the ids that are shown. `parts` is updated in place
    with the messages sent."""
    docs = await _docs(parts)
    total = sum(len(part["ids"]) for part in parts)
    decided = sum(1 for part in parts for job_id in part["ids"] if job_id in docs and mark(docs[job_id]))
    label = datetime.fromisoformat(day).strftime("%d.%m")
    shown: set[str] = set()
    first = 1
    for part in parts:
        present = [job_id for job_id in part["ids"] if job_id in docs]
        jobs = [Job.from_doc(docs[job_id]) for job_id in present]
        start, first = first, first + len(part["ids"])
        if not jobs:
            continue
        marks = [mark(docs[job_id]) for job_id in present]
        numbered = enumerate(zip(jobs, present, strict=True), start)
        view = _View(
            html=review_summary_html(jobs, start, total, day=label, decided=decided, marks=marks),
            plain=review_summary_plain(jobs, start, total, day=label, decided=decided, marks=marks),
            markup=get_job_summary_kb([(n, job.title or "", job_id) for n, (job, job_id) in numbered]),
        )
        if (part.get("message_id") and await _edit(bot, part, view)) or (send_new and await _send(bot, part, view)):
            shown.update(present)
    return shown


@dataclass
class _View:
    """One part of the day's summary, rendered: the rich text, its plain fallback, the buttons."""

    html: str
    plain: str
    markup: InlineKeyboardMarkup


async def _edit(bot: Bot, part: dict[str, Any], view: "_View") -> bool:
    """False when the message is gone (deleted by hand): the caller may send a new one."""
    for _ in range(_SEND_ATTEMPTS):
        try:
            if part.get("kind") == "plain":
                await bot.edit_message_text(
                    chat_id=part["chat_id"], message_id=part["message_id"], reply_markup=view.markup,
                    text=view.plain,
                )  # fmt: skip
            else:
                await bot.edit_message_text(
                    chat_id=part["chat_id"], message_id=part["message_id"], reply_markup=view.markup,
                    rich_message=InputRichMessage(html=view.html),
                )  # fmt: skip
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest as e:
            text = str(e).lower()
            if "not modified" in text:
                return True
            logger.info("Review summary: the message %s cannot be edited (%s)", part["message_id"], e)
            return False
        except TelegramAPIError:
            logger.warning("Review summary: editing failed", exc_info=True)
            return True  # still there; the next change tries again
    return True


async def _send(bot: Bot, part: dict[str, Any], view: "_View") -> bool:
    for _ in range(_SEND_ATTEMPTS):
        try:
            try:
                message = await bot.send_rich_message(
                    chat_id=settings.telegram_admin_id,
                    rich_message=InputRichMessage(html=view.html),
                    reply_markup=view.markup,
                    disable_notification=True,
                )
                kind = "rich"
            except TelegramBadRequest:
                logger.warning("Telegram refused the rich summary, sending the plain version", exc_info=True)
                message = await bot.send_message(
                    chat_id=settings.telegram_admin_id,
                    text=view.plain,
                    reply_markup=view.markup,
                    disable_notification=True,
                )
                kind = "plain"
        except TelegramRetryAfter as e:
            logger.warning("Telegram flood control, waiting %s s", e.retry_after)
            await asyncio.sleep(e.retry_after)
            continue
        except TelegramAPIError:
            logger.exception("Failed to send the review summary")
            return False
        part.update(chat_id=message.chat.id, message_id=message.message_id, kind=kind)
        return True
    logger.error("Gave up on the review summary after %d flood-control waits", _SEND_ATTEMPTS)
    return False
