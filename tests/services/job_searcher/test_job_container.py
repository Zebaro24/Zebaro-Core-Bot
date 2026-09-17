import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]

mock_jobs_collection = MagicMock()
mock_jobs_collection.insert_many = AsyncMock()
mock_jobs_collection.count_documents = AsyncMock()

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=mock_jobs_collection, start_db=AsyncMock())

from src.services.job_searcher.container import Job, JobStorage  # noqa: E402


def test_job_str():
    job = Job(
        platform_name="TestPlatform",
        job_id="123",
        title="Python Dev",
        company="TestCo",
        description="Some description",
        date=datetime(2025, 1, 1),
        link="https://test.com",
    )

    assert str(job) == "<TestPlatform - Python Dev - TestCo>"


def test_job_from_doc_ignores_mongo_only_keys_and_tolerates_old_documents():
    job = Job.from_doc(
        {"_id": "507f1f77bcf86cd799439011", "title": "Python Dev", "moderation": "sent", "user_status": "applied"}
    )

    assert job.title == "Python Dev"
    assert job.user_status == "applied"
    assert job.matched_stack == []  # documents stored before the field existed


def test_add_and_remove_job():
    storage = JobStorage()
    job = Job(title="Python Dev")

    storage.add_job(job)
    assert job in storage.jobs

    storage.remove_job(job)
    assert job not in storage.jobs


def test_log_jobs(caplog):
    storage = JobStorage()
    job1 = Job(title="Dev1")
    job2 = Job(title="Dev2")
    storage.add_job(job1)
    storage.add_job(job2)

    with caplog.at_level("INFO", logger="job_searcher.container"):
        storage.log_jobs()

    assert "Total new jobs: 2" in caplog.text


@pytest.mark.asyncio
async def test_save_jobs_to_db_returns_ids_in_order(mocker):
    storage = JobStorage()
    job1 = Job(title="Python Dev")
    job2 = Job(title="AI Engineer")
    storage.add_job(job1)
    storage.add_job(job2)

    patched = mocker.patch("src.services.job_searcher.container.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.insert_many.reset_mock()
    mock_jobs_collection.insert_many.return_value = MagicMock(inserted_ids=["id1", "id2"])

    ids = await storage.save_jobs_to_db()

    mock_jobs_collection.insert_many.assert_awaited_once()
    inserted_docs = mock_jobs_collection.insert_many.call_args[0][0]
    assert inserted_docs[0]["title"] == "Python Dev"
    assert ids == ["id1", "id2"]
    _ = patched  # used for patching side-effect


@pytest.mark.asyncio
async def test_save_jobs_to_db_no_jobs_returns_empty_list():
    storage = JobStorage()
    assert await storage.save_jobs_to_db() == []


@pytest.mark.asyncio
async def test_save_jobs_to_db_db_failure_returns_none_placeholders(mocker):
    storage = JobStorage()
    job = Job(title="Python Dev")
    storage.add_job(job)

    failing_collection = MagicMock()
    failing_collection.insert_many = AsyncMock(side_effect=Exception("no db"))
    patched = mocker.patch("src.services.job_searcher.container.jobs_collection", failing_collection)

    ids = await storage.save_jobs_to_db()

    assert ids == [None]
    _ = patched


@pytest.mark.asyncio
async def test_remove_jobs_already_in_db(mocker):
    storage = JobStorage()
    job = Job(platform_name="TestPlatform", job_id="123")
    storage.add_job(job)

    patched = mocker.patch("src.services.job_searcher.container.jobs_collection", mock_jobs_collection)
    mock_jobs_collection.count_documents.reset_mock()
    mock_jobs_collection.count_documents.return_value = 1

    await storage.remove_jobs_already_in_db()

    assert job not in storage.jobs
    mock_jobs_collection.count_documents.assert_awaited_once_with(
        {"platform_name": "TestPlatform", "job_id": "123"}, limit=1
    )
    _ = patched
