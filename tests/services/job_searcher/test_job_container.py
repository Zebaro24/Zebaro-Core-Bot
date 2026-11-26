import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]

sys.modules["src.config"] = MagicMock(settings=mock_settings)

from src.services.job_searcher import store  # noqa: E402
from src.services.job_searcher.container import REVISIT_DAYS, Job, JobStorage, already_seen_query  # noqa: E402


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
async def test_save_jobs_to_db_returns_ids_in_order(sql_db):
    storage = JobStorage()
    storage.add_job(Job(title="Python Dev", link="https://a"))
    storage.add_job(Job(title="AI Engineer", link="https://b", date="2 дні тому"))

    ids = await storage.save_jobs_to_db()

    assert len(ids) == 2 and all(store.valid_id(i) for i in ids)
    first, second = [await store.get(i or "") for i in ids]
    assert first is not None and second is not None
    assert (first["title"], second["title"]) == ("Python Dev", "AI Engineer")
    # A board's text date is read against when the vacancy was found: the column takes dates only.
    assert isinstance(second["date"], datetime) and second["date"] < second["found_at"]


@pytest.mark.asyncio
async def test_save_jobs_to_db_no_jobs_returns_empty_list():
    storage = JobStorage()
    assert await storage.save_jobs_to_db() == []


@pytest.mark.asyncio
async def test_save_jobs_to_db_db_failure_returns_none_placeholders(mocker):
    storage = JobStorage()
    storage.add_job(Job(title="Python Dev"))
    mocker.patch.object(store, "put", AsyncMock(side_effect=Exception("no db")))

    assert await storage.save_jobs_to_db() == [None]


@pytest.mark.asyncio
async def test_remove_jobs_already_in_db(sql_db):
    await store.put([{"platform_name": "TestPlatform", "job_id": "123", "found_at": datetime.utcnow()}])
    storage = JobStorage()
    seen, fresh = Job(platform_name="TestPlatform", job_id="123"), Job(platform_name="TestPlatform", job_id="124")
    storage.add_job(seen)
    storage.add_job(fresh)

    await storage.remove_jobs_already_in_db()

    assert storage.jobs == [fresh]


@pytest.mark.asyncio
async def test_an_old_unanswered_copy_no_longer_hides_a_live_vacancy(sql_db):
    # PwC 780338: stored in 11.2025 with no decision, bumped on Djinni a year later.
    now = datetime(2026, 11, 5, 12)
    query = already_seen_query("Djinni", "780338", now)

    async def hides(days_ago: int, status: str | None) -> bool:
        job_id = (await store.put([{"platform_name": "Djinni", "job_id": "780338", "user_status": status,
                                    "found_at": now - timedelta(days=days_ago)}]))[0]  # fmt: skip
        found = await store.count(query & (store.J.id == job_id))
        return found == 1

    assert not await hides(368, None)
    assert not await hides(REVISIT_DAYS + 1, "pending")
    assert await hides(REVISIT_DAYS - 1, None)  # recent: still the same vacancy
    assert await hides(368, "not_interested")  # answered: hidden for good
    # A same-run copy is marked a repeat whether or not anyone answered: not an answer itself.
    assert not await hides(368, "duplicate")
    # Another board's id is another vacancy.
    other = (
        await store.put([{"platform_name": "Dou", "job_id": "780338", "user_status": "applied", "found_at": now}])
    )[0]
    assert await store.count(query & (store.J.id == other)) == 0


def test_add_job_skips_a_vacancy_this_run_already_has():
    # DOU lists one vacancy on several searches and in the hot block: it must arrive once.
    storage = JobStorage()

    assert storage.add_job(Job(platform_name="Dou", job_id="374084", title="Python Dev"))
    assert not storage.add_job(Job(platform_name="Dou", job_id="374084", title="Python Dev"))
    assert storage.add_job(Job(platform_name="Djinni", job_id="374084"))  # same id, other site

    assert len(storage.jobs) == 2


def test_add_job_keeps_jobs_without_an_id():
    storage = JobStorage()
    storage.add_job(Job(title="Dev1"))
    storage.add_job(Job(title="Dev2"))

    assert len(storage.jobs) == 2
