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
    action_hours: list[float] = []

    for doc in docs:
        moderation = doc.get("moderation") or "rejected_by_filter"
        if moderation in totals:
            totals[moderation] += 1

        platform = doc.get("platform_name") or "Unknown"
        platform_stats = by_platform.setdefault(platform, {"found": 0, "sent": 0, "applied": 0, "not_interested": 0})
        platform_stats["found"] += 1
        if moderation == "sent":
            platform_stats["sent"] += 1

        if moderation == "rejected_by_filter":
            continue

        user_status = doc.get("user_status") or "pending"
        if user_status in by_status:
            by_status[user_status] += 1
        if user_status == "applied":
            platform_stats["applied"] += 1
        elif user_status == "not_interested":
            platform_stats["not_interested"] += 1

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
        "response_rate": response_rate,
        "avg_hours_to_action": avg_hours_to_action,
    }


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
