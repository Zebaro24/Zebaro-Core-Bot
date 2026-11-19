import asyncio
import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

import httpx
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage
from aiogram.types import Message
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.interfaces.tg.formatters.notify import notice_to_html
from src.interfaces.tg.notification import notify as delivery
from src.interfaces.webhooks.routes import notify as route
from src.services import notify as store
from src.services.notify import Notice

TOKEN = "notify-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _body(**overrides):
    body = {"project": "Zebaro-Core", "repo": "mcp", "event": "plan", "title": "план готов",
            "text": "Нужно твоё «го».", "session": "s1"}  # fmt: skip
    body.update(overrides)
    return body


@pytest_asyncio.fixture
async def records(tmp_path, mocker):
    """A real SQLite file with the notify table; `records.fail = True` breaks every session."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'notify.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(
            store.Base.metadata.create_all, tables=[store.Base.metadata.tables["notify_messages"]]
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    state = MagicMock(fail=False)

    def _open():
        if state.fail:
            raise OperationalError("SELECT", {}, Exception("database is locked"))
        return sessions()

    mocker.patch.object(store, "_open", _open)

    async def rows():
        async with sessions() as s:
            return [(r.project, r.session, r.message_id) for r in (await s.scalars(select(store.NotifyMessage))).all()]

    state.rows = rows
    yield state
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_limit():
    route.rate_limit.reset()
    yield
    route.rate_limit.reset()


@pytest.fixture
def settings(mocker):
    mocked = MagicMock(notify_api_token=TOKEN, telegram_admin_id=42)
    mocker.patch.object(route, "settings", mocked)
    mocker.patch.object(delivery, "settings", mocked)
    return mocked


@pytest.fixture
def bot():
    counter = iter(range(1, 1000))

    async def _send(**_):
        return MagicMock(message_id=next(counter))

    return MagicMock(send_message=AsyncMock(side_effect=_send), delete_message=AsyncMock())


@pytest.fixture
def app(settings, bot, records):
    app = FastAPI()
    app.state.bot = bot
    app.include_router(route.router, prefix="/notify")
    return app


@pytest.fixture
def call(app):
    async def _call(method, path="/notify", content=b"", headers=None):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://bot.zebaro.dev") as client:
            response = await client.request(method, path, content=content, headers=AUTH if headers is None else headers)
        return response

    return _call


@pytest.fixture
def post(call):
    async def _post(headers=None, **overrides):
        return (await call("POST", content=json.dumps(_body(**overrides)).encode(), headers=headers)).status_code

    return _post


def _deleted(bot):
    return [c.kwargs["message_id"] for c in bot.delete_message.await_args_list]


@pytest.mark.asyncio
async def test_a_notification_goes_to_the_owner_with_a_seen_button(post, bot, records):
    assert await post() == 202

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 42
    assert "Zebaro-Core · mcp" in kwargs["text"] and "план готов" in kwargs["text"]
    assert kwargs["reply_markup"].inline_keyboard[0][0].text == "✓"
    assert await records.rows() == [("Zebaro-Core", "s1", 1)]


@pytest.mark.asyncio
async def test_one_live_message_per_project(post, bot, records):
    await post()
    await post(session="s2", event="done", title="готово")
    await post(project="Neko", session="s3")

    assert _deleted(bot) == [1]
    assert sorted(row[2] for row in await records.rows()) == [2, 3]


@pytest.mark.asyncio
async def test_two_pings_at_once_still_leave_one_message(post, bot, records):
    counter = iter(range(1, 10))

    async def _slow_send(**_):
        message_id = next(counter)
        await asyncio.sleep(0.01)  # the other ping gets in while this one waits for Telegram
        return MagicMock(message_id=message_id)

    bot.send_message.side_effect = _slow_send
    assert list(await asyncio.gather(post(), post(session="s2"))) == [202, 202]

    assert len(await records.rows()) == 1
    assert len(_deleted(bot)) == 1


@pytest.mark.asyncio
async def test_a_failure_after_the_send_is_not_a_503(post, mocker):
    mocker.patch.object(store, "take_project", side_effect=RuntimeError("boom"))
    assert await post() == 202


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}])
@pytest.mark.asyncio
async def test_a_wrong_or_missing_token_is_refused(post, bot, headers):
    assert await post(headers=headers) == 401
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unset_token_closes_the_endpoint(call, settings):
    settings.notify_api_token = ""
    assert (await call("POST", headers={"Authorization": "Bearer "})).status_code == 401
    assert (await call("DELETE", "/notify?session=s1", headers={"Authorization": "Bearer "})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"{not json"])
async def test_a_tokenless_request_gets_401_whatever_the_body(call, content):
    assert (await call("POST", content=content, headers={})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides", [{"event": "spam"}, {"project": ""}, {"session": ""}, {"text": "x" * 1001}, {"title": ""}]
)
async def test_a_bad_body_with_the_token_is_a_422(post, overrides):
    assert await post(**overrides) == 422


@pytest.mark.asyncio
async def test_unknown_fields_are_ignored(post):
    assert await post(model="opus") == 202


@pytest.mark.asyncio
async def test_a_runaway_loop_is_stopped_at_120_an_hour(post):
    codes = [await post(session=f"s{i}") for i in range(121)]
    assert codes == [202] * 120 + [429]


@pytest.mark.asyncio
async def test_telegram_refusing_is_a_503_and_keeps_the_previous_message(post, bot, records):
    await post()
    bot.send_message.side_effect = RuntimeError("Bad Request: chat not found")

    assert await post(session="s2") == 503
    assert [row[2] for row in await records.rows()] == [1]
    bot.delete_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_bot_yet_is_a_503(app, post):
    app.state.bot = None
    assert await post() == 503


@pytest.mark.asyncio
async def test_the_database_failing_still_delivers(post, call, bot, records):
    records.fail = True
    assert await post() == 202
    bot.send_message.assert_awaited_once()
    assert (await call("DELETE", "/notify?session=s1")).json() == {"deleted": 0}


@pytest.mark.asyncio
async def test_the_owners_answer_clears_that_sessions_messages(post, call, bot, records):
    await post()
    await post(project="Neko", session="s2")

    response = await call("DELETE", "/notify?session=s1")

    assert response.status_code == 200 and response.json() == {"deleted": 1}
    assert _deleted(bot) == [1]
    assert [row[1] for row in await records.rows()] == ["s2"]


@pytest.mark.asyncio
async def test_clearing_an_unknown_session_deletes_nothing(call, bot):
    response = await call("DELETE", "/notify?session=nobody")
    assert response.json() == {"deleted": 0}
    bot.delete_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/notify", "/notify?session=", f"/notify?session={'x' * 129}"])
async def test_clearing_needs_a_session(call, path):
    assert (await call("DELETE", path)).status_code == 422


@pytest.mark.asyncio
async def test_a_message_already_gone_is_not_an_error(post, call, bot):
    await post()
    bot.delete_message.side_effect = TelegramBadRequest(
        DeleteMessage(chat_id=42, message_id=1), "message to delete not found"
    )
    assert (await call("DELETE", "/notify?session=s1")).json() == {"deleted": 1}


@pytest.mark.asyncio
async def test_the_sweep_takes_messages_older_than_12_hours(settings, bot, records):
    now = time.time()
    notice = Notice(**_body())
    await store.remember(notice, 7, now - 13 * 3600)
    await store.remember(notice.model_copy(update={"project": "Neko"}), 8, now - 3600)

    await delivery.notify_sweep(bot)

    assert _deleted(bot) == [7]
    assert [row[2] for row in await records.rows()] == [8]


@pytest.mark.asyncio
async def test_the_seen_button_deletes_its_message_and_record(records):
    await store.remember(Notice(**_body()), 5)
    message = MagicMock(spec=Message, message_id=5, delete=AsyncMock())
    query = MagicMock(message=message, answer=AsyncMock())

    await delivery.seen_callback(query)

    message.delete.assert_awaited_once()
    query.answer.assert_awaited_once()
    assert await records.rows() == []


def test_everything_sent_is_escaped():
    text = notice_to_html(Notice(**_body(project="<b>x</b>", repo=None, text="a & <i>b</i>", event="done")))
    assert text.startswith("✅ <b>&lt;b&gt;x&lt;/b&gt;</b> — план готов")
    assert " · " not in text
    assert "a &amp; &lt;i&gt;b&lt;/i&gt;" in text
