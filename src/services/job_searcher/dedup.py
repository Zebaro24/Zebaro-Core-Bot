"""One vacancy, one message: repeats across sites and reposts on the same site.

A group is the same title and company within LOOKBACK_DAYS, on any platform — Djinni reposts a
vacancy under a new id, and DOU and Djinni list the same one. The owner pressing a button on one
copy decides for the whole group, so the statistics count one decision per vacancy.

Within a run the copies of one vacancy collapse into a single message: the copy on the most
useful site is sent (Djinni last — it refuses applications that miss its experience gate) and
the others become link buttons. Against the history:

* the group was answered (applied / not interested) → the repeat is not sent at all;
* Djinni would not let him apply ("blocked") → a copy on another site is sent with that note,
  another Djinni repost is not;
* the group is still unanswered → the repeat is sent with 🔁 and when it came first.

Repeats that are not sent are stored with user_status "duplicate" and never counted.
"""

import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from bson import ObjectId

from src.db.client import jobs_collection
from src.services.job_searcher.container import Job

logger = logging.getLogger("job_searcher.dedup")

# Title likeness once the company matched. High on purpose: a false match hides a vacancy.
SIMILARITY_THRESHOLD = 0.85
LOOKBACK_DAYS = 30

# Which copy of a vacancy is the one to open. Djinni is last: its experience gate refuses an
# application the other boards would take for the same position.
PLATFORM_PRIORITY = ("Dou", "Work.ua", "Robota.ua", "No Fluff Jobs", "HappyMonday", "BazaIT", "Wellfound", "Djinni")
_UNKNOWN_RANK = PLATFORM_PRIORITY.index("Djinni") - 0.5

DECIDED = ("applied", "not_interested")
BLOCKED = "blocked"
DUPLICATE = "duplicate"
PENDING = "pending"

_COMPANY_SUFFIXES = ("llc", "ооо", "тов", "фоп", "inc", "ltd", "gmbh")


def _normalize_company(company: str | None) -> str:
    text = (company or "").lower().strip()
    for suffix in _COMPANY_SUFFIXES:
        if text.endswith(f" {suffix}"):
            text = text[: -len(suffix) - 1].strip()
        elif text.startswith(f"{suffix} "):
            text = text[len(suffix) + 1 :].strip()
    return text


def _normalize_title(title: str | None) -> str:
    return " ".join((title or "").lower().split())


def same_vacancy(a_title: str | None, a_company: str | None, b_title: str | None, b_company: str | None) -> bool:
    """The same position: the company matches and the title is the same up to punctuation.

    Title and company are compared apart. Glued together, the long shared company name made
    "Python Developer" and "Go Developer" at one company look alike — and a repeat is hidden,
    so a false match costs a vacancy. For the same reason a title that only extends another
    is not a match: VCHASNO had "Python Developer" and "Middle Python Developer" open at once.
    """
    title_a, title_b = _normalize_title(a_title), _normalize_title(b_title)
    if not title_a or not title_b:
        return False
    company_a, company_b = _normalize_company(a_company), _normalize_company(b_company)
    if company_a or company_b:
        same_company = company_a == company_b or (
            bool(company_a and company_b) and (company_a in company_b or company_b in company_a)
        )
        if not same_company:
            return False
    elif title_a != title_b:
        return False  # no company on either side: only an exact title is safe
    return title_a == title_b or SequenceMatcher(None, title_a, title_b).ratio() >= SIMILARITY_THRESHOLD


def _rank(platform: str | None) -> float:
    return PLATFORM_PRIORITY.index(platform) if platform in PLATFORM_PRIORITY else _UNKNOWN_RANK


def group_root(doc: dict[str, Any]) -> str:
    """The group a stored vacancy belongs to; documents from before groups are their own."""
    return str(doc.get("group_id") or doc["_id"])


def group_state(docs: list[dict[str, Any]]) -> tuple[str, set[str]]:
    """What the owner already said about a group, and on which platforms he was blocked."""
    blocked_on = {doc.get("platform_name") or "" for doc in docs if doc.get("user_status") == BLOCKED}
    if any(doc.get("user_status") in DECIDED for doc in docs):
        return "decided", blocked_on
    return (BLOCKED if blocked_on else PENDING), blocked_on


def _clusters(pairs: list[tuple[Job, str | None]]) -> list[list[tuple[Job, str | None]]]:
    """Copies of one vacancy inside this run, the best copy first."""
    clusters: list[list[tuple[Job, str | None]]] = []
    for pair in sorted(pairs, key=lambda p: (_rank(p[0].platform_name), -p[0].relevance_score)):
        job = pair[0]
        for cluster in clusters:
            first = cluster[0][0]
            if same_vacancy(job.title, job.company, first.title, first.company):
                cluster.append(pair)
                break
        else:
            clusters.append([pair])
    return clusters


async def _recent_docs(exclude: set[str]) -> list[dict[str, Any]]:
    since = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    docs = jobs_collection.find({"found_at": {"$gte": since}, "moderation": {"$ne": "rejected_by_filter"}})
    return [doc async for doc in docs if str(doc.get("_id")) not in exclude]


def _apply_history(cluster: list[tuple[Job, str | None]], recent: list[dict[str, Any]]) -> None:
    primary = cluster[0][0]
    earlier = next(
        (doc for doc in recent if same_vacancy(primary.title, primary.company, doc.get("title"), doc.get("company"))),
        None,
    )
    if earlier is None:
        return

    root = group_root(earlier)
    state, blocked_on = group_state([doc for doc in recent if group_root(doc) == root])
    for job, _ in cluster:
        job.group_id = root
    primary.similar_to = str(earlier["_id"])
    primary.similar_to_platform = earlier.get("platform_name")
    primary.similar_seen_at = earlier.get("found_at")
    primary.similar_status = state

    # Answered already, or only more copies on the site that refused him: nothing new to see.
    if state == "decided" or (state == BLOCKED and primary.platform_name in blocked_on):
        primary.user_status = DUPLICATE


async def group_duplicates(jobs: list[Job], job_ids: list[str | None]) -> None:
    """Group this run's vacancies with each other and with the last LOOKBACK_DAYS; store it.

    Runs after the batch is saved: the copies need their Mongo ids for the link buttons.
    """
    pairs = [(job, job_id) for job, job_id in zip(jobs, job_ids) if job.moderation != "rejected_by_filter"]
    if not pairs:
        return

    clusters = _clusters(pairs)
    for cluster in clusters:
        primary, primary_id = cluster[0]
        primary.group_id = primary_id
        primary.copies = [{"platform": job.platform_name, "id": job_id} for job, job_id in cluster[1:] if job_id]
        for job, _ in cluster[1:]:
            job.group_id = primary_id
            job.user_status = DUPLICATE
            job.similar_to = primary_id
            job.similar_to_platform = primary.platform_name

    try:
        recent = await _recent_docs({job_id for _, job_id in pairs if job_id})
    except Exception as e:
        logger.warning("DB unavailable for the repeat check, sending the batch as it is: %s", e)
        return

    for cluster in clusters:
        _apply_history(cluster, recent)

    await _store(pairs)
    repeats = sum(1 for job, _ in pairs if job.user_status == DUPLICATE)
    if repeats:
        logger.info("Repeats not sent: %d of %d", repeats, len(pairs))


async def _store(pairs: list[tuple[Job, str | None]]) -> None:
    for job, job_id in pairs:
        if not job_id or not job.group_id:
            continue
        try:
            await jobs_collection.update_one(
                {"_id": ObjectId(job_id)},
                {
                    "$set": {
                        "group_id": job.group_id,
                        "user_status": job.user_status,
                        "copies": job.copies,
                        "similar_to": job.similar_to,
                        "similar_to_platform": job.similar_to_platform,
                        "similar_seen_at": job.similar_seen_at,
                        "similar_status": job.similar_status,
                    }
                },
            )
        except Exception as e:
            logger.warning("Could not store the group of %s: %s", job, e)
