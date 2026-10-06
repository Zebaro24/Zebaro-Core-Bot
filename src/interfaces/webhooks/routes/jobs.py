import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from src.config import settings
from src.db.client import jobs_collection
from src.services.job_searcher.digest import get_digest
from src.services.job_searcher.stats import get_pending_review_jobs, get_search_stats, get_weekly_stats

logger = logging.getLogger("webhooks.jobs")

router = APIRouter()

# Module level: flake8-bugbear (B008) rejects a call in an argument default.
_DAYS_QUERY = Query(7, ge=1, le=180)
_SEARCH_DAYS_QUERY = Query(30, ge=1, le=365)
_SEARCH_LIMIT_QUERY = Query(50, ge=1, le=500)
_SKIP_QUERY = Query(0, ge=0)
_SEARCHES_DAYS_QUERY = Query(30, ge=1, le=365)

# Search skips the long description unless asked (with_description) - e.g. to hand
# the applied vacancies to an AI for analysis.
_SEARCH_PROJECTION = {"description": 0}


def _check_token(request: Request) -> None:
    authorization = request.headers.get("Authorization") or ""
    if not settings.job_stats_api_token or not secrets.compare_digest(
        authorization, f"Bearer {settings.job_stats_api_token}"
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


@router.get("/stats/weekly")
async def weekly_stats(request: Request, days: int = _DAYS_QUERY) -> dict[str, Any]:
    _check_token(request)
    return await get_weekly_stats(days)


@router.get("/stats/digest")
async def digest_stats(request: Request, days: int = _DAYS_QUERY) -> dict[str, Any]:
    """The weekly digest's numbers: the market and the owner's decisions."""
    _check_token(request)
    digest: dict[str, Any] = to_jsonable(await get_digest(days))
    return digest


@router.get("/stats/searches")
async def search_stats(request: Request, days: int = _SEARCHES_DAYS_QUERY) -> list[dict[str, Any]]:
    """Every search URL: found, sent, answered, why the rest was filtered out."""
    _check_token(request)
    return await get_search_stats(days)


@router.get("/review")
async def pending_review(request: Request) -> list[dict[str, Any]]:
    _check_token(request)
    return await get_pending_review_jobs()


def to_jsonable(value: Any) -> Any:
    """ObjectId and datetime to plain strings, recursively, so FastAPI can encode a document."""
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def build_search_query(
    q: str | None,
    platform: str | None,
    moderation: str | None,
    status: str | None,
    reason: str | None,
    days: int,
    status_reason: str | None = None,
    search_url: str | None = None,
) -> dict[str, Any]:
    """Fixed-shape filter: every user value is an exact match or an escaped regex."""
    query: dict[str, Any] = {"found_at": {"$gte": datetime.utcnow() - timedelta(days=days)}}
    if q:
        pattern = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"title": pattern}, {"company": pattern}]
    if platform:
        query["platform_name"] = {"$regex": f"^{re.escape(platform)}$", "$options": "i"}
    if moderation:
        query["moderation"] = moderation
    if status:
        query["user_status"] = status
    if reason:
        query["filter_reason"] = {"$regex": re.escape(reason), "$options": "i"}
    if status_reason:
        query["status_reason"] = status_reason
    if search_url:
        query["search_url"] = {"$regex": re.escape(search_url), "$options": "i"}
    return query


async def _find_jobs(
    query: dict[str, Any], limit: int, projection: dict[str, int] | None = None, skip: int = 0
) -> list[dict[str, Any]]:
    try:
        cursor = jobs_collection.find(query, projection).sort("found_at", -1).skip(skip).limit(limit)
        return [to_jsonable(doc) async for doc in cursor]
    except Exception as e:
        logger.warning("DB unavailable for job query: %s", e)
        raise HTTPException(status_code=503, detail="Job storage unavailable") from None


@router.get("/job/{job_id}")
async def job_details(request: Request, job_id: str) -> dict[str, Any]:
    """One vacancy in full: by our _id (the one in the Telegram buttons) or the platform's job_id."""
    _check_token(request)
    query: dict[str, Any] = {"job_id": job_id}
    if ObjectId.is_valid(job_id):
        query = {"$or": [{"_id": ObjectId(job_id)}, query]}
    docs = await _find_jobs(query, 1)
    if not docs:
        raise HTTPException(status_code=404, detail="Job not found")
    return docs[0]


@router.get("/search")
async def search_jobs(
    request: Request,
    q: str | None = None,
    platform: str | None = None,
    moderation: str | None = None,
    status: str | None = None,
    reason: str | None = None,
    status_reason: str | None = None,
    search_url: str | None = None,
    days: int = _SEARCH_DAYS_QUERY,
    limit: int = _SEARCH_LIMIT_QUERY,
    skip: int = _SKIP_QUERY,
    with_description: bool = False,
) -> list[dict[str, Any]]:
    """Stored vacancies, newest first; `skip` pages past the 500 cap (the replay reads them all)."""
    _check_token(request)
    query = build_search_query(q, platform, moderation, status, reason, days, status_reason, search_url)
    return await _find_jobs(query, limit, None if with_description else _SEARCH_PROJECTION, skip)


@router.get("/r/{job_id}")
async def redirect_to_job(job_id: str) -> RedirectResponse:
    try:
        object_id = ObjectId(job_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Job not found") from None

    try:
        doc = await jobs_collection.find_one_and_update({"_id": object_id}, {"$inc": {"click_count": 1}})
    except Exception as e:
        logger.warning("DB unavailable for job redirect: %s", e)
        raise HTTPException(status_code=503, detail="Job storage unavailable") from None

    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    return RedirectResponse(url=doc["link"], status_code=302)
