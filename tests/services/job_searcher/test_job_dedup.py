import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]

mock_jobs_collection = MagicMock()

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=mock_jobs_collection, start_db=AsyncMock())

from src.services.job_searcher.container import Job  # noqa: E402
from src.services.job_searcher.dedup import _is_similar, _normalize, mark_cross_platform_duplicates  # noqa: E402


def _async_cursor(docs):
    async def _gen():
        for doc in docs:
            yield doc

    return _gen()


@pytest.mark.parametrize(
    "title,company,expected",
    [
        ("Python Developer", "TechCorp LLC", "python developer techcorp"),
        ("Python Developer", "ТОВ Техкорп", "python developer техкорп"),
        (None, None, ""),
    ],
)
def test_normalize_strips_company_suffixes(title, company, expected):
    assert _normalize(title, company) == expected


def test_is_similar_identical_strings():
    assert _is_similar("python developer techcorp", "python developer techcorp") is True


def test_is_similar_different_strings():
    assert _is_similar("python developer techcorp", "java qa engineer school") is False


def test_is_similar_empty_strings_never_match():
    assert _is_similar("", "python developer") is False


@pytest.mark.asyncio
async def test_mark_cross_platform_duplicates_matches_recent_db_job(mocker):
    job = Job(title="Python Developer", company="TechCorp", platform_name="Djinni", moderation="sent")

    mocker.patch("src.services.job_searcher.dedup.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(
        [
            {
                "_id": "existing123",
                "title": "Python Developer",
                "company": "TechCorp",
                "platform_name": "Work.ua",
                "found_at": datetime.utcnow(),
            }
        ]
    )

    await mark_cross_platform_duplicates([job], ["new_id_1"])

    assert job.similar_to == "existing123"
    assert job.similar_to_platform == "Work.ua"


@pytest.mark.asyncio
async def test_mark_cross_platform_duplicates_skips_same_platform(mocker):
    job = Job(title="Python Developer", company="TechCorp", platform_name="Djinni", moderation="sent")

    mocker.patch("src.services.job_searcher.dedup.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(
        [
            {
                "_id": "existing123",
                "title": "Python Developer",
                "company": "TechCorp",
                "platform_name": "Djinni",
                "found_at": datetime.utcnow(),
            }
        ]
    )

    await mark_cross_platform_duplicates([job], ["new_id_1"])

    assert job.similar_to is None


@pytest.mark.asyncio
async def test_mark_cross_platform_duplicates_skips_rejected_jobs(mocker):
    job = Job(
        title="Python Developer",
        company="TechCorp",
        platform_name="Djinni",
        moderation="rejected_by_filter",
    )

    mocker.patch("src.services.job_searcher.dedup.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.find.return_value = _async_cursor(
        [
            {
                "_id": "existing123",
                "title": "Python Developer",
                "company": "TechCorp",
                "platform_name": "Work.ua",
                "found_at": datetime.utcnow(),
            }
        ]
    )

    await mark_cross_platform_duplicates([job], ["new_id_1"])

    assert job.similar_to is None


@pytest.mark.asyncio
async def test_mark_cross_platform_duplicates_db_unavailable_is_silent(mocker):
    job = Job(title="Python Developer", company="TechCorp", platform_name="Djinni", moderation="sent")

    failing_collection = MagicMock()
    failing_collection.find.side_effect = Exception("no db")
    mocker.patch("src.services.job_searcher.dedup.jobs_collection", failing_collection)

    await mark_cross_platform_duplicates([job], ["new_id_1"])

    assert job.similar_to is None
