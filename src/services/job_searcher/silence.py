"""S3: an application nobody answered is a refusal — `no_response`, set by the bot.

Daily at 10:00: a vacancy at `applied` whose last event is older than NO_RESPONSE_DAYS (21) goes
to `rejected_by_employer` / `no_response`, `actor: system`, with a silent edit of its message.
"No event" is read from `history`, so the daily run waits for the backfill (backfill.py): until
the old applications have their restored events, it does nothing. The backfill turns the
silence that piled up before the release down once, without Telegram.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from src.config import settings
from src.db.client import jobs_collection, meta_collection
from src.services.job_searcher.jobs_api import public_status
from src.services.job_searcher.status import StatusConflict, write_status

logger = logging.getLogger("job_searcher.silence")

BACKFILL_ID = "jobs_backfill"
NO_RESPONSE = "no_response"
SILENCE_JOB_ID = "job_no_response"
SILENCE_HOUR = 10


def last_event_at(history: list[dict[str, Any]]) -> datetime | None:
    moments = [event["occurred_at"] for event in history if isinstance(event.get("occurred_at"), datetime)]
    return max(moments) if moments else None


def is_silent(doc: dict[str, Any], cutoff: datetime) -> bool:
    """At "applied", with a history, and nothing in it since `cutoff`."""
    if public_status(doc) != "applied":
        return False
    last = last_event_at(doc.get("history") or [])
    return last is not None and last < cutoff


async def backfill_done() -> bool:
    return await meta_collection.find_one({"_id": BACKFILL_ID}) is not None


async def turn_down_silent(days: int, *, sync: bool, approximate: bool, now: datetime | None = None) -> int:
    """Every silent application → no_response. How many were turned down."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=days)
    query = {"user_status": "applied", "outcome": None, "history.occurred_at": {"$lt": cutoff}}
    turned = 0
    async for doc in jobs_collection.find(query, {"description": 0}):
        last = last_event_at(doc.get("history") or [])
        if last is None or not is_silent(doc, cutoff):
            continue
        # The refusal is dated when the silence reached its length, not when the bot noticed:
        # the backfill turns months of it down at once, and by=event must not see a spike that day.
        try:
            await write_status(
                doc, "rejected_by_employer", expected="applied", actor="system", reason_code=NO_RESPONSE,
                reason=f"Нет ответа {days} дней", occurred_at=last + timedelta(days=days),
                approximate=approximate, sync=sync,
            )  # fmt: skip
            turned += 1
        except StatusConflict:  # changed while the run went through the list
            continue
    return turned


async def silence_job() -> int:
    """The daily run (the scheduler, 10:00)."""
    try:
        if not await backfill_done():
            logger.info("No-response check skipped: the history backfill has not run yet")
            return 0
        turned = await turn_down_silent(settings.no_response_days, sync=True, approximate=False)
    except Exception as e:  # MongoDB down: tomorrow's run sees the same applications
        logger.warning("No-response check failed: %s", e)
        return 0
    if turned:
        logger.info("Applications turned down for silence: %d", turned)
    return turned
