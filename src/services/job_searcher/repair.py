"""One-off repairs of the stored vacancies, run when the service is enabled (05.11.2026).

* **found_at.** The 363 vacancies of 10–11.2025 were stored before the field existed, so every
  Jobs API query by period missed them. The insert time is in their `_id`.
* **Djinni dates.** Djinni writes the card's time on Kyiv's clock, and it was stored as UTC:
  up to three hours ahead, often after the moment the vacancy was found. Each shifted copy is
  marked `date_utc`, and only copies stored before the first run of this repair are touched —
  the parser stores UTC since, so a crash halfway or a second start never shifts one twice.
* **Same-run copies.** Until 23.09.2026 a vacancy listed by several searches of a site was
  stored once per search (69 vacancies, up to four copies). Each copy counted as found, and the
  owner's buttons on two messages counted twice. The copy that got furthest stays; the others
  become repeats of it, the way a copy on another site is one.

All three are idempotent; the state is in `meta.jobs_repair`.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId

from src.db.client import jobs_collection, meta_collection
from src.services.job_searcher.dedup import DUPLICATE, group_root
from src.services.job_searcher.jobs_api import public_status, stage_rank
from src.services.job_searcher.listeners.djinni import kyiv_to_utc
from src.services.job_searcher.status import new_event

logger = logging.getLogger("job_searcher.repair")

REPAIR_ID = "jobs_repair"
# Copies of one id stored this close together came from one run, not from a later repost.
SAME_RUN = timedelta(seconds=60)
SAME_RUN_CAUSE = "same_run_copy"


async def fill_found_at() -> int:
    filled = 0
    async for doc in jobs_collection.find({"found_at": {"$exists": False}}, {"_id": 1}):
        found_at = doc["_id"].generation_time.replace(tzinfo=None)
        await jobs_collection.update_one({"_id": doc["_id"]}, {"$set": {"found_at": found_at}})
        filled += 1
    return filled


async def _djinni_cutoff(now: datetime) -> ObjectId:
    """The first start of this repair: copies stored after it already hold UTC."""
    state = await meta_collection.find_one_and_update(
        {"_id": REPAIR_ID},
        {"$setOnInsert": {"djinni_utc_before": ObjectId.from_datetime(now)}},
        upsert=True,
        return_document=True,
    )
    cutoff = (state or {}).get("djinni_utc_before")
    if not isinstance(cutoff, ObjectId):  # the document existed without it
        cutoff = ObjectId.from_datetime(now)
        await meta_collection.update_one({"_id": REPAIR_ID}, {"$set": {"djinni_utc_before": cutoff}})
    return cutoff


async def djinni_dates_to_utc(now: datetime) -> int:
    cutoff = await _djinni_cutoff(now)
    query = {"platform_name": "Djinni", "date": {"$type": "date"}, "date_utc": {"$ne": True}, "_id": {"$lt": cutoff}}
    shifted = 0
    async for doc in jobs_collection.find(query, {"date": 1}):
        await jobs_collection.update_one(
            {"_id": doc["_id"], "date_utc": {"$ne": True}},
            {"$set": {"date": kyiv_to_utc(doc["date"]), "date_utc": True}},
        )
        shifted += 1
    return shifted


def _furthest(copies: list[dict[str, Any]]) -> dict[str, Any]:
    """The copy to keep: the furthest status, then an answer over none, clicks, the oldest."""

    def key(doc: dict[str, Any]) -> tuple:
        status = public_status(doc)
        return (
            -stage_rank(status, doc.get("status_reason")),
            status == "new",
            -int(doc.get("click_count") or 0),
            doc["_id"],
        )

    return min(copies, key=key)


def same_run_groups(docs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Copies of one id stored within SAME_RUN of the first, two or more of them not repeats yet."""
    by_id: dict[tuple, list[dict[str, Any]]] = {}
    for doc in docs:
        by_id.setdefault((doc.get("platform_name"), doc.get("job_id")), []).append(doc)
    groups = []
    for copies in by_id.values():
        copies.sort(key=lambda doc: doc["_id"])
        while copies:
            first = copies[0]["_id"].generation_time
            run = [doc for doc in copies if doc["_id"].generation_time - first <= SAME_RUN]
            copies = copies[len(run) :]
            if sum(doc.get("user_status") != DUPLICATE for doc in run) > 1:
                groups.append(run)
    return groups


async def mark_same_run_copies(now: datetime) -> int:
    pipeline: list[dict[str, Any]] = [
        {"$match": {"job_id": {"$ne": None}}},
        {"$group": {"_id": {"p": "$platform_name", "j": "$job_id"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
    ]
    keys = [row["_id"] async for row in await jobs_collection.aggregate(pipeline)]
    if not keys:
        return 0
    fields = {"platform_name": 1, "job_id": 1, "user_status": 1, "outcome": 1, "status_reason": 1,
              "status_reason_text": 1, "click_count": 1, "group_id": 1}  # fmt: skip
    query = {"$or": [{"platform_name": key.get("p"), "job_id": key.get("j")} for key in keys]}
    docs = [doc async for doc in jobs_collection.find(query, fields)]
    marked = 0
    for run in same_run_groups(docs):
        keep = _furthest([doc for doc in run if doc.get("user_status") != DUPLICATE])
        root = group_root(keep)
        for doc in run:
            if doc["_id"] == keep["_id"] or doc.get("user_status") == DUPLICATE:
                continue
            event = new_event(
                doc, DUPLICATE, actor="system", occurred_at=now, now=now, approximate=False, cause=SAME_RUN_CAUSE
            )
            # Compare-and-set: the webhook is live while the service starts — a button pressed on
            # the copy meanwhile wins, and the copy is left for the next start.
            result = await jobs_collection.update_one(
                {"_id": doc["_id"], "user_status": doc.get("user_status")},
                {
                    "$set": {
                        "user_status": DUPLICATE,
                        "group_id": root,
                        "similar_to": str(keep["_id"]),
                        "similar_to_platform": doc.get("platform_name"),
                    },
                    "$push": {"history": event},
                },
            )
            if not result.modified_count:
                continue
            marked += 1
            # Copies on other boards grouped under the dropped one follow it to the kept one.
            if (old_root := group_root(doc)) != root:
                await jobs_collection.update_many({"group_id": old_root}, {"$set": {"group_id": root}})
    return marked


async def run_repairs() -> None:
    """Each repair on its own: one that fails must not stop the others or the service."""
    now = datetime.utcnow()
    for name, repair in (
        ("found_at filled", fill_found_at),
        ("Djinni dates moved from Kyiv time to UTC", lambda: djinni_dates_to_utc(now)),
        ("same-run copies marked as repeats", lambda: mark_same_run_copies(now)),
    ):
        try:
            if count := await repair():
                logger.info("Stored vacancies, %s: %d", name, count)
        except Exception as e:
            logger.warning("Repair failed (%s): %s", name, e)
