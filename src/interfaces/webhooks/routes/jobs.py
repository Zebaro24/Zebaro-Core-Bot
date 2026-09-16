import logging
import secrets
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.config import settings
from src.db.client import jobs_collection
from src.services.job_searcher.stats import get_pending_review_jobs, get_weekly_stats

logger = logging.getLogger("webhooks.jobs")

router = APIRouter()


def _check_token(request: Request) -> None:
    authorization = request.headers.get("Authorization") or ""
    if not settings.job_stats_api_token or not secrets.compare_digest(
        authorization, f"Bearer {settings.job_stats_api_token}"
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


@router.get("/stats/weekly")
async def weekly_stats(request: Request) -> dict[str, Any]:
    _check_token(request)
    return await get_weekly_stats()


@router.get("/review")
async def pending_review(request: Request) -> list[dict[str, Any]]:
    _check_token(request)
    return await get_pending_review_jobs()


@router.get("/r/{job_id}")
async def redirect_to_job(job_id: str) -> RedirectResponse:
    try:
        object_id = ObjectId(job_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        doc = await jobs_collection.find_one_and_update({"_id": object_id}, {"$inc": {"click_count": 1}})
    except Exception as e:
        logger.warning("DB unavailable for job redirect: %s", e)
        raise HTTPException(status_code=503, detail="Job storage unavailable")

    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    return RedirectResponse(url=doc["link"], status_code=302)
