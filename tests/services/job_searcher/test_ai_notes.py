import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from bson import ObjectId

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from fake_jobs import FakeJobs  # (pytest puts this directory on sys.path)

from src.interfaces.tg.notification import ai_notes
from src.interfaces.tg.notification.ai_notes import CURRENT, NOTES_PER_MESSAGE, SESSION


def _vacancy(n: int, to: str = "not_interested", code: str | None = "role", reason: str | None = None):
    event = {"id": f"ev{n}", "from": "new", "to": to, "actor": "ai", "reason_code": code, "reason": reason}
    doc = {
        "_id": ObjectId(f"{n:024x}"),
        "title": f"Engineer {n}",
        "company": f"Co{n}",
        "user_status": to,
        "status_reason": code,
        "history": [event],
    }
    return doc, event


@pytest.fixture
def stores(mocker):
    jobs, meta = FakeJobs(), FakeJobs()
    mocker.patch.object(ai_notes, "jobs_collection", jobs)
    mocker.patch.object(ai_notes, "meta_collection", meta)
    return jobs, meta


def _bot():
    bot = MagicMock()
    counter = iter(range(500, 600))

    async def send(**_):
        return MagicMock(chat=MagicMock(id=1), message_id=next(counter))

    bot.send_message = AsyncMock(side_effect=send)
    bot.edit_message_text = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_changes_of_one_session_go_into_one_message(stores):
    jobs, meta = stores
    bot = _bot()
    for n in range(3):
        doc, event = _vacancy(n, reason="Embedded, не software" if n == 1 else None)
        jobs.docs.append(doc)
        await ai_notes.add_note(bot, doc, event)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["disable_notification"] is True
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert text.startswith("🤖 <b>AI: 3 изменения</b>")
    assert "Без решения → <b>Не интересно</b>" in text
    assert "<i>Embedded, не software</i>" in text
    assert len(meta.by_id("ai_notes:500")["entries"]) == 3


@pytest.mark.asyncio
async def test_a_pause_or_a_full_message_starts_a_new_one(stores):
    jobs, meta = stores
    bot = _bot()
    doc, event = _vacancy(0)
    jobs.docs.append(doc)
    await ai_notes.add_note(bot, doc, event)
    meta.by_id(CURRENT)["last_at"] = datetime.utcnow() - SESSION - timedelta(minutes=1)

    doc, event = _vacancy(1)
    jobs.docs.append(doc)
    await ai_notes.add_note(bot, doc, event)
    assert bot.send_message.await_count == 2

    for n in range(2, NOTES_PER_MESSAGE + 2):
        doc, event = _vacancy(n)
        jobs.docs.append(doc)
        await ai_notes.add_note(bot, doc, event)
    assert bot.send_message.await_count == 3
    assert len(meta.by_id("ai_notes:501")["entries"]) == NOTES_PER_MESSAGE


@pytest.mark.asyncio
async def test_a_retried_change_is_not_listed_twice(stores):
    jobs, meta = stores
    bot = _bot()
    doc, event = _vacancy(0)
    jobs.docs.append(doc)
    await ai_notes.add_note(bot, doc, event)
    await ai_notes.add_note(bot, doc, event)

    assert len(meta.by_id("ai_notes:500")["entries"]) == 1


@pytest.mark.asyncio
async def test_a_deleted_message_starts_a_new_one(stores):
    jobs, _ = stores
    bot = _bot()
    bot.edit_message_text.side_effect = TelegramBadRequest(method=MagicMock(), message="message to edit not found")
    for n in range(2):
        doc, event = _vacancy(n)
        jobs.docs.append(doc)
        await ai_notes.add_note(bot, doc, event)

    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_the_choice_lists_what_can_be_undone_and_an_undone_change_is_struck_through(stores):
    jobs, _ = stores
    bot = _bot()
    for n in range(2):
        doc, event = _vacancy(n)
        jobs.docs.append(doc)
        await ai_notes.add_note(bot, doc, event)

    await ai_notes.refresh(bot, 1, 500, picking=True)
    markup = bot.edit_message_text.await_args.kwargs["reply_markup"]
    texts = [button.text for row in markup.inline_keyboard for button in row]
    assert texts == ["↩️ 1. Co0", "↩️ 2. Co1", "✖️ Назад"]

    undo = {"id": "ev9", "from": "not_interested", "to": "new", "actor": "user", "undo_of": "ev0"}
    jobs.docs[0]["history"].append(undo)
    jobs.docs[0]["user_status"] = "pending"
    await ai_notes.refresh(bot, 1, 500)
    edit = bot.edit_message_text.await_args.kwargs
    assert "<s>1. Co0 — Engineer 0</s> ↩️ отменено" in edit["text"]
    assert [button.text for row in edit["reply_markup"].inline_keyboard for button in row] == ["↩️ Отменить…"]


@pytest.mark.asyncio
async def test_an_unknown_message_is_not_refreshed(stores):
    assert await ai_notes.refresh(_bot(), 1, 999) is False


@pytest.mark.asyncio
async def test_long_notes_move_to_a_new_message_before_telegrams_limit(stores):
    jobs, _ = stores
    bot = _bot()
    for n in range(NOTES_PER_MESSAGE):
        doc, event = _vacancy(n, reason="Обязательны " + "очень длинные требования " * 10)
        doc["title"] = "Senior Principal Engineer " * 4
        jobs.docs.append(doc)
        await ai_notes.add_note(bot, doc, event)

    assert bot.send_message.await_count >= 2
    for call in bot.edit_message_text.await_args_list:
        assert len(call.kwargs["text"]) <= ai_notes.MAX_TEXT
