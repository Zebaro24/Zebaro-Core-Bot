import logging
from datetime import datetime, timedelta
from typing import Any

from src.db.client import jobs_collection

logger = logging.getLogger("job_searcher.stats")


async def get_weekly_stats(days: int = 7) -> dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)
    try:
        docs = [doc async for doc in jobs_collection.find({"found_at": {"$gte": since}})]
    except Exception as e:
        logger.warning("DB unavailable for weekly stats: %s", e)
        docs = []

    totals = {"found": len(docs), "sent": 0, "review": 0, "rejected_by_filter": 0}
    by_platform: dict[str, dict[str, int]] = {}
    by_status = {"applied": 0, "not_interested": 0, "pending": 0}
    # Why vacancies were not sent — what to look at when tuning the filter.
    by_reason: dict[str, int] = {}
    # Which technologies the owner actually answers to: the same counts for what he applied
    # to and what he waved off. This is what the filter's weights should follow.
    stack_applied: dict[str, int] = {}
    stack_rejected: dict[str, int] = {}
    action_hours: list[float] = []

    for doc in docs:
        moderation = doc.get("moderation") or "rejected_by_filter"
        if moderation in totals:
            totals[moderation] += 1

        platform = doc.get("platform_name") or "Unknown"
        platform_stats = by_platform.setdefault(platform, _empty_platform_stats())
        platform_stats["found"] += 1
        if moderation == "sent":
            platform_stats["sent"] += 1
        elif moderation == "review":
            platform_stats["review"] += 1
        platform_stats["clicks"] += int(doc.get("click_count") or 0)

        if moderation == "rejected_by_filter":
            reason = doc.get("filter_reason")
            if reason:
                by_reason[reason] = by_reason.get(reason, 0) + 1
            continue

        user_status = doc.get("user_status") or "pending"
        if user_status in by_status:
            by_status[user_status] += 1
        if user_status == "applied":
            platform_stats["applied"] += 1
            _count_stack(stack_applied, doc)
        elif user_status == "not_interested":
            platform_stats["not_interested"] += 1
            _count_stack(stack_rejected, doc)

        status_updated_at = doc.get("status_updated_at")
        found_at = doc.get("found_at")
        if user_status != "pending" and status_updated_at and found_at:
            action_hours.append((status_updated_at - found_at).total_seconds() / 3600)

    surfaced = totals["sent"] + totals["review"]
    response_rate = by_status["applied"] / surfaced if surfaced > 0 else None
    avg_hours_to_action = sum(action_hours) / len(action_hours) if action_hours else None

    return {
        "period_days": days,
        "totals": totals,
        "by_platform": [{"platform": platform, **stats} for platform, stats in sorted(by_platform.items())],
        "by_status": by_status,
        "by_reason": dict(sorted(by_reason.items(), key=lambda item: -item[1])),
        "stack_applied": _sorted_by_count(stack_applied),
        "stack_rejected": _sorted_by_count(stack_rejected),
        # With nothing found at all (an empty period, or the DB down) every source would be
        # reported as silent, which says nothing.
        "silent_sources": silent_sources(by_platform) if docs else [],
        "response_rate": response_rate,
        "avg_hours_to_action": avg_hours_to_action,
    }


def _empty_platform_stats() -> dict[str, int]:
    return {"found": 0, "sent": 0, "review": 0, "applied": 0, "not_interested": 0, "clicks": 0}


def _count_stack(counter: dict[str, int], doc: dict[str, Any]) -> None:
    for name in (doc.get("matched_stack") or []) + (doc.get("matched_bonus") or []):
        counter[name] = counter.get(name, 0) + 1


def _sorted_by_count(counter: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: -item[1]))


def silent_sources(by_platform: dict[str, dict[str, int]]) -> list[str]:
    """Platforms that are searched but brought nothing — a broken selector or a block."""
    from src.services.job_searcher.parser import platform_names

    return sorted(name for name in platform_names() if not by_platform.get(name, {}).get("found"))


async def get_pending_review_jobs(days: int = 14) -> list[dict[str, Any]]:
    since = datetime.utcnow() - timedelta(days=days)
    try:
        docs = [
            doc
            async for doc in jobs_collection.find(
                {"moderation": "review", "user_status": "pending", "found_at": {"$gte": since}}
            )
        ]
    except Exception as e:
        logger.warning("DB unavailable for pending review jobs: %s", e)
        return []

    for doc in docs:
        doc["_id"] = str(doc["_id"])
    return docs
