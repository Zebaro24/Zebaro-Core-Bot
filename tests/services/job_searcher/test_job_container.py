import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]

mock_jobs_collection = MagicMock()
mock_jobs_collection.insert_many = AsyncMock()
mock_jobs_collection.count_documents = AsyncMock()

sys.modules["app.config"] = MagicMock(settings=mock_settings)
sys.modules["app.db.client"] = MagicMock(jobs_collection=mock_jobs_collection, start_db=AsyncMock())

from app.services.job_searcher.job_container import Job, JobStorage  # noqa: E402


def test_job_str_and_print(capsys):
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

    job.print_job()
    captured = capsys.readouterr()
    assert "Platform Name: TestPlatform" in captured.out
    assert "Job ID: 123" in captured.out
    assert "Title: Python Dev" in captured.out
    assert "Company: TestCo" in captured.out


def test_add_and_remove_job():
    storage = JobStorage()
    job = Job(title="Python Dev")

    storage.add_job(job)
    assert job in storage.jobs

    storage.remove_job(job)
    assert job not in storage.jobs


def test_print_jobs(capsys):
    storage = JobStorage()
    job1 = Job(title="Dev1")
    job2 = Job(title="Dev2")

    storage.add_job(job1)
    storage.add_job(job2)

    storage.print_jobs()
    captured = capsys.readouterr()

    assert "Всего 2 вакансий" in captured.out
    assert "Dev1" in captured.out
    assert "Dev2" in captured.out


@pytest.mark.asyncio
async def test_save_jobs_to_db():
    storage = JobStorage()
    job = Job(title="Python Dev")
    storage.add_job(job)

    mock_jobs_collection.insert_many.reset_mock()
    await storage.save_jobs_to_db()

    mock_jobs_collection.insert_many.assert_awaited_once()
    inserted_docs = mock_jobs_collection.insert_many.call_args[0][0]
    assert inserted_docs[0]["title"] == "Python Dev"


@pytest.mark.asyncio
async def test_remove_jobs_already_in_db():
    storage = JobStorage()
    job = Job(platform_name="TestPlatform", job_id="123")
    storage.add_job(job)

    mock_jobs_collection.count_documents.reset_mock()
    mock_jobs_collection.count_documents.return_value = 1

    await storage.remove_jobs_already_in_db()

    assert job not in storage.jobs
    mock_jobs_collection.count_documents.assert_awaited_once_with(
        {"platform_name": "TestPlatform", "job_id": "123"}, limit=1
    )
