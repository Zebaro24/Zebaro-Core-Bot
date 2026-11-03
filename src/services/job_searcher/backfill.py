"""One-off data work for the status history (Jobs API part B). Run inside the bot's container:

    python -m src.services.job_searcher.backfill                 # dry run: numbers only
    python -m src.services.job_searcher.backfill --apply         # restore, then the silence
    python -m src.services.job_searcher.backfill relabel --status rejected_by_employer \\
        --suggested relocation_required --code location [--apply]

**restore.** Vacancies decided before the history get their events back from the stored fields:
`new → applied` at `status_updated_at`, then `applied → <outcome>` at `outcome_at`; a "no" is one
`new → <status>` event. All `actor: system`, `approximate: true`, `restored: true`. Where events
were already written after the release, the restored ones go **before the first real one** and
end on its `from` — the chain reads without a gap — and dates past that event are not trusted
(a later write moved them), the vacancy's `found_at` stands in. A vacancy whose first event
starts at `new` needs nothing: that is also what makes a second run a no-op.

**silence.** Applications whose last event is older than NO_RESPONSE_DAYS become
`no_response` (`actor: system`, `approximate: true`), with no Telegram at all. Then the marker
`meta.jobs_backfill` is set, and the daily check (silence.py) starts working.

**relabel.** Events stored as `other` with a `suggested_code` that is now a real code get it.
"""

import argparse
import asyncio
import logging
import secrets
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from src.config import settings
from src.db.client import jobs_collection, meta_collection
from src.services.job_searcher.jobs_api import public_status
from src.services.job_searcher.reasons import OTHER, REASONS
from src.services.job_searcher.silence import BACKFILL_ID, is_silent, turn_down_silent

logger = logging.getLogger("job_searcher.backfill")

_OUTCOME_OF = {"replied", "interview", "offer", "rejected_by_employer"}


def _trusted(moment: Any, doc: dict[str, Any], limit: datetime | None) -> datetime | None:
    """A stored date that can be the time of a restored event: not before found_at, before `limit`."""
    if not isinstance(moment, datetime):
        return None
    found_at = doc.get("found_at")
    if isinstance(found_at, datetime) and moment < found_at:
        return None
    # The first real event's own write sets these dates to its time: at it or later is not ours.
    if limit is not None and moment >= limit:
        return None
    return moment


def _event(frm: str, to: str, at: datetime, now: datetime, code: str | None, reason: str | None) -> dict[str, Any]:
    return {
        "id": secrets.token_hex(6),
        "occurred_at": at,
        "recorded_at": now,
        "from": frm,
        "to": to,
        "actor": "system",
        "reason_code": code,
        "suggested_code": None,
        "reason": reason,
        "evidence": None,
        "approximate": True,
        "from_reason_code": None,
        "from_reason": None,
        "restored": True,
    }


def restored_events(doc: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """The events to put before the history (or to start it with); [] when nothing is missing."""
    history = doc.get("history") or []
    if history:
        first = history[0]
        target, limit = first.get("from") or "new", first.get("occurred_at")
        code, reason = first.get("from_reason_code"), first.get("from_reason")
    else:
        target, limit = public_status(doc), None
        code, reason = doc.get("status_reason"), doc.get("status_reason_text")
    if target == "new":
        return []
    stored = doc.get("found_at")
    found_at: datetime = stored if isinstance(stored, datetime) else now
    if isinstance(limit, datetime):
        found_at = min(found_at, limit)
    else:
        limit = None
    decided_at = _trusted(doc.get("status_updated_at"), doc, limit) or found_at
    if target not in _OUTCOME_OF:
        return [_event("new", target, decided_at, now, code, reason)]
    applied = _event("new", "applied", decided_at, now, None, None)
    if target == "applied":
        return [applied]
    outcome_at = _trusted(doc.get("outcome_at"), doc, limit)
    answered_at = outcome_at if outcome_at is not None and outcome_at >= decided_at else decided_at
    return [applied, _event("applied", target, answered_at, now, code, reason)]


async def restore(apply: bool, now: datetime | None = None) -> Counter[str]:
    """Restore the missing events; the counts by what was restored (also in a dry run)."""
    now = now or datetime.utcnow()
    counts: Counter[str] = Counter()
    query = {"$or": [{"user_status": {"$ne": "pending"}}, {"history": {"$ne": None}}]}
    async for doc in jobs_collection.find(query, {"description": 0}):
        events = restored_events(doc, now)
        if not events:
            continue
        history = doc.get("history") or []
        counts[f"to {events[-1]['to']}"] += 1
        counts["partial history" if history else "no history"] += 1
        if not _trusted(doc.get("status_updated_at"), doc, history[0]["occurred_at"] if history else None):
            counts["date from found_at"] += 1
        if apply:
            # Only if the history is still what was read: a live write meanwhile wins, a rerun fixes it.
            result = await jobs_collection.update_one(
                {"_id": doc["_id"], "history": doc.get("history")}, {"$set": {"history": events + history}}
            )
            counts["written"] += result.modified_count
    return counts


async def silent_count(now: datetime | None = None) -> int:
    """How many applications the silence step turns down — after the restore, as in a dry run."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=settings.no_response_days)
    turned = 0
    async for doc in jobs_collection.find({"user_status": "applied", "outcome": None}, {"description": 0}):
        events = restored_events(doc, now) + (doc.get("history") or [])
        turned += is_silent({**doc, "history": events}, cutoff)
    return turned


async def relabel(status: str, suggested: str, code: str, apply: bool) -> int:
    """`other` + `suggested_code` → the code; the vacancy's current reason too when it is that event."""
    if code not in REASONS.get(status, {}) or code == OTHER:
        raise SystemExit(f"{code!r} is not a code of {status!r} in reasons.py: add it there first")
    changed = 0
    query = {"history.suggested_code": suggested, "history.reason_code": OTHER}
    async for doc in jobs_collection.find(query, {"description": 0}):
        history = doc["history"]
        hits = [
            e
            for e in history
            if e.get("to") == status and e.get("reason_code") == OTHER and e.get("suggested_code") == suggested
        ]
        if not hits:
            continue
        changed += len(hits)
        if not apply:
            continue
        new_history = [{**e, "reason_code": code} if e in hits else e for e in history]
        change: dict[str, Any] = {"history": new_history}
        if history[-1] in hits and doc.get("status_reason") == OTHER:
            change["status_reason"] = code
        await jobs_collection.update_one({"_id": doc["_id"], "history": history}, {"$set": change})
    return changed


async def run(apply: bool) -> None:
    now = datetime.utcnow()
    counts = await restore(apply=False, now=now)
    silent = await silent_count(now)
    print("restore:", dict(counts) or "nothing to restore")
    print(f"silence: {silent} applications with no event for {settings.no_response_days}+ days → no_response")
    if not apply:
        print("dry run: nothing written; --apply to write")
        return
    written = await restore(apply=True, now=now)
    turned = await turn_down_silent(settings.no_response_days, sync=False, approximate=True, now=now)
    await meta_collection.update_one(
        {"_id": BACKFILL_ID},
        {"$set": {"done_at": now, "restored": written.get("written", 0), "no_response": turned}},
        upsert=True,
    )
    print(f"written: {written.get('written', 0)} restored, {turned} turned down; the daily check is on")


def main() -> None:
    parser = argparse.ArgumentParser(description="Status history backfill (Jobs API part B)")
    parser.add_argument("command", nargs="?", default="backfill", choices=("backfill", "relabel"))
    parser.add_argument("--apply", action="store_true", help="write; without it, a dry run")
    parser.add_argument("--status", default="rejected_by_employer")
    parser.add_argument("--suggested")
    parser.add_argument("--code")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "relabel":
        if not (args.suggested and args.code):
            parser.error("relabel needs --suggested and --code")
        count = asyncio.run(relabel(args.status, args.suggested, args.code, args.apply))
        print(f"relabel: {count} events {'changed' if args.apply else 'would change (dry run)'}")
        return
    asyncio.run(run(args.apply))


if __name__ == "__main__":
    main()
