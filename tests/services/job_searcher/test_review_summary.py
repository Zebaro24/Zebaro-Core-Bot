import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())

from fake_jobs import SqlJobs, SqlMeta

from src.interfaces.tg.notification import review_summary
from src.interfaces.tg.notification.review_summary import SUMMARY_CHUNK, place


def _doc(n: int, **fields):
    return {
        "_id": f"{n:024x}",
        "title": f"Engineer {n}",
        "company": "Acme",
        "platform_name": "Dou",
        "moderation": "review",
        "user_status": "pending",
        "found_at": datetime(2026, 11, 16),
        **fields,
    }


@pytest.fixture
def stores(sql_db, mocker):
    jobs, meta = SqlJobs(sql_db, mocker), SqlMeta(sql_db)
    mocker.patch.object(review_summary, "today", return_value="2026-11-16")
    return jobs, meta


def _bot(first_id: int = 100):
    bot = MagicMock()
    counter = iter(range(first_id, first_id + 100))

    async def send(**_):
        return MagicMock(chat=MagicMock(id=1), message_id=next(counter))

    bot.send_rich_message = AsyncMock(side_effect=send)
    bot.edit_message_text = AsyncMock()
    return bot


def test_place_fills_the_last_part_and_opens_a_new_one_past_the_chunk():
    parts = place([], [f"id{n}" for n in range(SUMMARY_CHUNK + 3)])
    assert [len(part["ids"]) for part in parts] == [SUMMARY_CHUNK, 3]

    again = place(parts, ["id0", "new"])  # a vacancy already shown is not added twice
    assert [len(part["ids"]) for part in again] == [SUMMARY_CHUNK, 4]
    assert len(parts[-1]["ids"]) == 3  # the input stays as it was


@pytest.mark.asyncio
async def test_a_later_run_edits_the_days_message_instead_of_sending_another(stores):
    jobs, meta = stores
    jobs.docs.extend(_doc(n) for n in range(3))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()

    assert await review_summary.add_to_summary(bot, ids[:2]) == 2
    assert await review_summary.add_to_summary(bot, ids[2:]) == 1

    bot.send_rich_message.assert_awaited_once()
    assert bot.send_rich_message.await_args.kwargs["disable_notification"] is True
    edit = bot.edit_message_text.await_args
    assert edit.kwargs["message_id"] == 100
    assert "Частичные совпадения за 16.11 — 3" in edit.kwargs["rich_message"].html
    assert meta.by_id("review_summary:2026-11-16")["parts"][0]["ids"] == ids
    assert all(doc["review_day"] == "2026-11-16" for doc in jobs.docs)


@pytest.mark.asyncio
async def test_a_new_day_starts_a_new_message(stores, mocker):
    jobs, _ = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()

    await review_summary.add_to_summary(bot, ids[:1])
    mocker.patch.object(review_summary, "today", return_value="2026-11-17")
    await review_summary.add_to_summary(bot, ids[1:])

    assert bot.send_rich_message.await_count == 2
    bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_deleted_message_is_sent_again(stores):
    jobs, meta = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()
    await review_summary.add_to_summary(bot, ids[:1])
    bot.edit_message_text.side_effect = TelegramBadRequest(method=MagicMock(), message="message to edit not found")

    await review_summary.add_to_summary(bot, ids[1:])

    assert bot.send_rich_message.await_count == 2
    assert meta.by_id("review_summary:2026-11-16")["parts"][0]["message_id"] == 101


@pytest.mark.asyncio
async def test_a_decided_vacancy_gets_its_status_mark_on_the_next_sync(stores):
    jobs, _ = stores
    jobs.docs.extend(_doc(n) for n in range(2))
    ids = [str(doc["_id"]) for doc in jobs.docs]
    bot = _bot()
    await review_summary.add_to_summary(bot, ids)
    jobs.docs[1].update(user_status="not_interested", status_reason="role", review_stale=True)

    assert await review_summary.refresh_stale_summaries(bot) == 1

    html = bot.edit_message_text.await_args.kwargs["rich_message"].html
    assert "(решено 1)" in html
    assert "<p>2. 👎 <b>Engineer 1</b>" in html
    assert jobs.docs[1].get("review_stale") is None
    bot.send_rich_message.assert_awaited_once()  # a refresh never sends a new message
