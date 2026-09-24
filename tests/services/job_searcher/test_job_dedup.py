import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]

mock_jobs_collection = MagicMock()

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=mock_jobs_collection, start_db=AsyncMock())

from src.services.job_searcher.container import Job  # noqa: E402
from src.services.job_searcher.dedup import (  # noqa: E402
    DUPLICATE,
    _normalize_company,
    group_duplicates,
    group_root,
    group_state,
    same_vacancy,
)

SEEN = datetime(2026, 9, 21, 12, 0)


def _async_cursor(docs):
    async def _gen():
        for doc in docs:
            yield doc

    return _gen()


@pytest.fixture
def collection(mocker):
    collection = MagicMock()
    collection.update_one = AsyncMock()
    mocker.patch("src.services.job_searcher.dedup.jobs_collection", collection)
    return collection


def _history(collection, docs):
    collection.find = MagicMock(return_value=_async_cursor(docs))


def _job(platform="Dou", title="Python Developer", company="TechCorp", score=10):
    return Job(title=title, company=company, platform_name=platform, moderation="sent", relevance_score=score)


def _doc(platform="Djinni", status="pending", group_id=None, title="Python Developer"):
    return {
        "_id": ObjectId(),
        "title": title,
        "company": "TechCorp",
        "platform_name": platform,
        "user_status": status,
        "found_at": SEEN,
        "group_id": group_id,
    }


def _ids(n):
    return [str(ObjectId()) for _ in range(n)]


@pytest.mark.parametrize(
    "company,expected",
    [("TechCorp LLC", "techcorp"), ("ТОВ Техкорп", "техкорп"), (None, "")],
)
def test_normalize_company_strips_suffixes(company, expected):
    assert _normalize_company(company) == expected


@pytest.mark.parametrize(
    "a,b,same",
    [
        (("Python Developer", "TechCorp"), ("python  developer", "TechCorp LLC"), True),
        # A title that extends another may be a second position: VCHASNO had both open at once.
        (("Python Developer", "VCHASNO"), ("Middle Python Developer", "VCHASNO"), False),
        (("Python Developer", "EPAM"), ("Python Developer", "EPAM Systems"), True),
        (("Full-Stack Engineer", "Akvelon"), ("Full Stack Engineer", "Akvelon"), True),
        # One company, two positions: glued with the company name these used to look alike.
        (("Python Developer", "TechCorp"), ("Go Developer", "TechCorp"), False),
        (("Python Developer", "TechCorp"), ("Python Developer", "OtherCo"), False),
        (("Python Developer", None), ("Python Developer", None), True),
        (("Python Developer", None), ("Python Dev", None), False),  # no company: exact title only
        ((None, "TechCorp"), ("Python Developer", "TechCorp"), False),
    ],
)
def test_same_vacancy(a, b, same):
    assert same_vacancy(*a, *b) is same


@pytest.mark.asyncio
async def test_copies_in_one_run_become_one_message_on_the_best_site(collection):
    _history(collection, [])
    djinni, dou, other = _job("Djinni", score=40), _job("Dou", score=10), _job("Dou", title="Go Developer")
    ids = _ids(3)

    await group_duplicates([djinni, dou, other], ids)

    # DOU wins over a better-scored Djinni copy: Djinni's experience gate refuses applications.
    assert dou.user_status == "pending"
    assert dou.copies == [{"platform": "Djinni", "id": ids[0]}]
    assert djinni.user_status == DUPLICATE
    assert djinni.group_id == dou.group_id == ids[1]
    assert other.user_status == "pending" and other.copies == []


@pytest.mark.asyncio
async def test_a_repost_on_the_same_site_of_an_answered_vacancy_is_not_sent(collection):
    # Djinni reposts under a new id: the old cross-platform check never saw it.
    earlier = _doc("Djinni", status="not_interested")
    _history(collection, [earlier])
    repost = _job("Djinni")

    await group_duplicates([repost], _ids(1))

    assert repost.user_status == DUPLICATE
    assert repost.group_id == str(earlier["_id"])
    collection.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unanswered_repeat_comes_with_when_it_was_first_sent(collection):
    earlier = _doc("Djinni", status="pending")
    _history(collection, [earlier])
    job = _job("Dou")

    await group_duplicates([job], _ids(1))

    assert job.user_status == "pending"
    assert (job.similar_status, job.similar_to_platform, job.similar_seen_at) == ("pending", "Djinni", SEEN)


@pytest.mark.asyncio
async def test_blocked_on_djinni_lets_the_dou_copy_through_but_not_another_djinni_one(collection):
    earlier = _doc("Djinni", status="blocked")
    _history(collection, [earlier])
    dou = _job("Dou")
    await group_duplicates([dou], _ids(1))
    assert dou.user_status == "pending" and dou.similar_status == "blocked"

    _history(collection, [earlier])
    repost = _job("Djinni")
    await group_duplicates([repost], _ids(1))
    assert repost.user_status == DUPLICATE


@pytest.mark.asyncio
async def test_a_group_answered_on_any_copy_counts_as_answered(collection):
    root = _doc("Dou", status="pending")
    answered = _doc("Djinni", status="applied", group_id=str(root["_id"]), title="Totally renamed")
    _history(collection, [root, answered])
    job = _job("Work.ua")

    await group_duplicates([job], _ids(1))

    assert job.user_status == DUPLICATE
    assert job.group_id == str(root["_id"])


@pytest.mark.asyncio
async def test_rejected_by_filter_is_left_alone(collection):
    _history(collection, [_doc(status="applied")])
    job = _job()
    job.moderation = "rejected_by_filter"

    await group_duplicates([job], _ids(1))

    assert job.user_status == "pending" and job.group_id is None
    collection.find.assert_not_called()


@pytest.mark.asyncio
async def test_db_down_still_collapses_the_run(collection):
    collection.find = MagicMock(side_effect=Exception("no db"))
    first, second = _job("Dou"), _job("Djinni")

    await group_duplicates([first, second], _ids(2))

    assert second.user_status == DUPLICATE
    collection.update_one.assert_not_awaited()


def test_group_state_and_root():
    doc = _doc()
    assert group_root(doc) == str(doc["_id"])
    assert group_root({**doc, "group_id": "abc"}) == "abc"
    assert group_state([_doc(status="pending")]) == ("pending", set())
    assert group_state([_doc("Djinni", status="blocked")]) == ("blocked", {"Djinni"})
    assert group_state([_doc(status="blocked"), _doc(status="applied")])[0] == "decided"
