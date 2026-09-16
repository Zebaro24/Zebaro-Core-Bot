import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from src.db.client import jobs_collection
from src.services.job_searcher.container import Job

logger = logging.getLogger("job_searcher.dedup")

SIMILARITY_THRESHOLD = 0.82
LOOKBACK_DAYS = 14

_COMPANY_SUFFIXES = ("llc", "ооо", "тов", "фоп", "inc", "ltd", "gmbh")


def _normalize_company(company: str | None) -> str:
    text = (company or "").lower().strip()
    for suffix in _COMPANY_SUFFIXES:
        if text.endswith(f" {suffix}"):
            text = text[: -len(suffix) - 1].strip()
        elif text.startswith(f"{suffix} "):
            text = text[len(suffix) + 1 :].strip()
    return text


def _normalize(title: str | None, company: str | None) -> str:
    return f"{(title or '').lower().strip()} {_normalize_company(company)}".strip()


def _is_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD


async def mark_cross_platform_duplicates(jobs: list[Job], job_ids: list[str | None]) -> None:
    if not jobs:
        return

    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    try:
        recent_docs = [
            doc
            async for doc in jobs_collection.find(
                {"found_at": {"$gte": since}, "moderation": {"$ne": "rejected_by_filter"}}
            )
        ]
    except Exception as e:
        logger.warning("DB unavailable for cross-platform dedup, skipping: %s", e)
        return

    matched = 0
    for job, job_id in zip(jobs, job_ids):
        if job.moderation == "rejected_by_filter":
            continue
        key = _normalize(job.title, job.company)
        for doc in recent_docs:
            if str(doc.get("_id")) == job_id or doc.get("platform_name") == job.platform_name:
                continue
            if _is_similar(key, _normalize(doc.get("title"), doc.get("company"))):
                job.similar_to = str(doc["_id"])
                job.similar_to_platform = doc.get("platform_name")
                matched += 1
                break

    if matched:
        logger.info("Marked %d jobs as cross-platform duplicates", matched)
