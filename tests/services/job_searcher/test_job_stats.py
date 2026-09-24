import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]

mock_jobs_collection = MagicMock()

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=mock_jobs_collection, start_db=AsyncMock())

from src.services.job_searcher.stats import get_pending_review_jobs, get_weekly_stats  # noqa: E402


def _async_cursor(docs):
    async def _gen():
        for doc in docs:
            yield doc

    return _gen()


def _job_doc(
    platform_name="Djinni",
    moderation="sent",
    user_status="pending",
    found_at=None,
    status_updated_at=None,
):
    return {
        "platform_name": platform_name,
        "moderation": moderation,
        "user_status": user_status,
        "found_at": found_at or datetime.utcnow(),
        "status_updated_at": status_updated_at,
    }


@pytest.mark.asyncio
async def test_get_weekly_stats_totals_and_by_platform(mocker):
    now = datetime.utcnow()
    docs = [
        _job_doc(platform_name="Djinni", moderation="sent", user_status="applied", status_updated_at=now),
        _job_doc(platform_name="Djinni", moderation="review", user_status="pending"),
        _job_doc(platform_name="Work.ua", moderation="sent", user_status="not_interested", status_updated_at=now),
        _job_doc(platform_name="Work.ua", moderation="rejected_by_filter", user_status="pending"),
        # A repeat of an answered vacancy: neither a new vacancy nor a second decision.
        _job_doc(platform_name="Djinni", moderation="sent", user_status="duplicate"),
    ]
    mocker.patch("src.services.job_searcher.stats.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(docs)

    stats = await get_weekly_stats(days=7)

    assert stats["totals"] == {"found": 4, "sent": 2, "review": 1, "rejected_by_filter": 1, "repeats": 1}
    assert stats["by_status"] == {"applied": 1, "not_interested": 1, "blocked": 0, "pending": 1}

    by_platform = {p["platform"]: {k: v for k, v in p.items() if k != "platform"} for p in stats["by_platform"]}
    djinni = {"found": 2, "sent": 1, "review": 1, "applied": 1, "not_interested": 0, "blocked": 0, "clicks": 0}
    work_ua = {"found": 2, "sent": 1, "review": 0, "applied": 0, "not_interested": 1, "blocked": 0, "clicks": 0}
    assert by_platform["Djinni"] == djinni
    assert by_platform["Work.ua"] == work_ua


@pytest.mark.asyncio
async def test_get_weekly_stats_counts_why_vacancies_were_not_sent(mocker):
    docs = [
        {**_job_doc(moderation="rejected_by_filter"), "filter_reason": "senior"},
        {**_job_doc(moderation="rejected_by_filter"), "filter_reason": "senior"},
        {**_job_doc(moderation="rejected_by_filter"), "filter_reason": "no stack match"},
        _job_doc(moderation="rejected_by_filter"),  # stored before reasons existed
        _job_doc(moderation="sent"),
    ]
    mocker.patch("src.services.job_searcher.stats.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(docs)

    stats = await get_weekly_stats(days=7)

    assert stats["by_reason"] == {"senior": 2, "no stack match": 1}
    assert list(stats["by_reason"]) == ["senior", "no stack match"]


@pytest.mark.asyncio
async def test_get_weekly_stats_response_rate_and_avg_hours(mocker):
    found_at = datetime.utcnow() - timedelta(hours=10)
    status_updated_at = datetime.utcnow()
    docs = [
        _job_doc(moderation="sent", user_status="applied", found_at=found_at, status_updated_at=status_updated_at),
        _job_doc(moderation="review", user_status="pending"),
    ]
    mocker.patch("src.services.job_searcher.stats.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(docs)

    stats = await get_weekly_stats(days=7)

    assert stats["response_rate"] == pytest.approx(0.5)
    assert stats["avg_hours_to_action"] == pytest.approx(10, abs=0.01)


@pytest.mark.asyncio
async def test_get_weekly_stats_no_surfaced_jobs_response_rate_is_none(mocker):
    docs = [_job_doc(moderation="rejected_by_filter", user_status="pending")]
    mocker.patch("src.services.job_searcher.stats.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(docs)

    stats = await get_weekly_stats(days=7)

    assert stats["response_rate"] is None
    assert stats["avg_hours_to_action"] is None


@pytest.mark.asyncio
async def test_get_weekly_stats_db_unavailable_returns_empty_stats(mocker):
    failing_collection = MagicMock()
    failing_collection.find.side_effect = Exception("no db")
    mocker.patch("src.services.job_searcher.stats.jobs_collection", failing_collection)

    stats = await get_weekly_stats(days=7)

    assert stats["totals"] == {"found": 0, "sent": 0, "review": 0, "rejected_by_filter": 0, "repeats": 0}
    assert stats["by_platform"] == []


@pytest.mark.asyncio
async def test_get_pending_review_jobs_filters_and_stringifies_id(mocker):
    docs = [{"_id": "abc123", "title": "Python Dev"}]
    mocker.patch("src.services.job_searcher.stats.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(docs)

    result = await get_pending_review_jobs(days=14)

    assert result == [{"_id": "abc123", "title": "Python Dev"}]
    call_args = mock_jobs_collection.find.call_args[0][0]
    assert call_args["moderation"] == "review"
    assert call_args["user_status"] == "pending"
