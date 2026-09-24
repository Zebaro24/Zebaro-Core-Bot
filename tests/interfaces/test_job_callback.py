import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from bson import ObjectId

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.tg.handlers.callbacks import job as callback  # noqa: E402
from src.interfaces.tg.keyboards.job import JobActionCallback  # noqa: E402


def _async_cursor(docs):
    async def _gen():
        for doc in docs:
            yield doc

    return _gen()


def _doc(platform="Dou", status="pending", group_id=None):
    return {"_id": ObjectId(), "title": "Python Developer", "platform_name": platform, "user_status": status,
            "group_id": group_id}  # fmt: skip


@pytest.fixture
def collection(mocker):
    collection = MagicMock()
    collection.update_many = AsyncMock()
    mocker.patch.object(callback, "jobs_collection", collection)
    return collection


def _setup(collection, doc, group):
    collection.find_one = AsyncMock(return_value=doc)
    collection.find = MagicMock(return_value=_async_cursor(group))

    async def update(query, change, **_kwargs):
        return {**doc, **change["$set"]}

    collection.find_one_and_update = AsyncMock(side_effect=update)


def _query():
    message = MagicMock(spec=Message)
    message.rich_message = None
    message.html_text = "vacancy"
    message.edit_text = AsyncMock()
    query = MagicMock()
    query.message = message
    query.answer = AsyncMock()
    return query


async def _press(action, doc):
    query = _query()
    await callback.job_action_callback(query, JobActionCallback(action=action, job_id=str(doc["_id"])))
    return query


@pytest.mark.asyncio
async def test_an_answer_closes_the_copies_still_waiting_in_the_chat(collection):
    doc = _doc("Dou")
    waiting = _doc("Djinni", group_id=str(doc["_id"]))
    _setup(collection, doc, [doc, waiting])

    query = await _press("apply", doc)

    assert collection.find_one_and_update.await_args.args[1]["$set"]["user_status"] == "applied"
    closed = collection.update_many.await_args.args[0]
    assert closed["_id"]["$in"] == [waiting["_id"]] and closed["user_status"] == "pending"
    assert "Откликнулся" in query.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_a_second_answer_on_another_copy_is_not_counted_again(collection):
    root = _doc("Dou", status="applied")
    doc = _doc("Djinni", group_id=str(root["_id"]))
    _setup(collection, doc, [root, doc])

    query = await _press("reject", doc)

    # Stored as a repeat, and the message says what was decided and where.
    assert collection.find_one_and_update.await_args.args[1]["$set"]["user_status"] == "duplicate"
    collection.update_many.assert_not_awaited()
    assert "Откликнулся (на Dou)" in query.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
async def test_djinni_blocking_keeps_the_group_open(collection):
    doc = _doc("Djinni")
    _setup(collection, doc, [doc])

    query = await _press("block", doc)

    assert collection.find_one_and_update.await_args.args[1]["$set"]["user_status"] == "blocked"
    collection.update_many.assert_not_awaited()
    assert "Не пускает" in query.message.edit_text.await_args.args[0]
