import hashlib
import hmac
import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

import httpx
import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.interfaces.tg.formatters import github as fmt
from src.interfaces.tg.handlers.admin import github as admin
from src.interfaces.tg.notification import github as delivery
from src.interfaces.webhooks.routes import github as route
from src.services.github import store
from src.services.github.events import Alert, Outside, Push, Release, Run
from src.services.github.service import GithubService

ADMIN = 42
FORUM = -100500
REPO = "Zebaro24/Zebaro-Core-MCP"
SECRET = "hook-secret"


@pytest_asyncio.fixture
async def db(tmp_path, mocker):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gh.db'}")
    async with engine.begin() as connection:
        tables = [store.Base.metadata.tables[t] for t in ("github_topics", "github_repos", "github_messages")]
        await connection.run_sync(store.Base.metadata.create_all, tables=tables)
    mocker.patch.object(store, "_open", async_sessionmaker(engine, expire_on_commit=False))
    delivery._broken.clear()
    yield
    await engine.dispose()


@pytest.fixture
def settings(mocker):
    mocked = MagicMock(telegram_admin_id=ADMIN, gh_webhook_secret=SECRET)
    mocker.patch.object(delivery, "settings", mocked)
    mocker.patch.object(route, "settings", mocked)
    return mocked


@pytest.fixture
def bot():
    counter = iter(range(100, 1000))

    async def _send(chat_id, text, **kwargs):
        return MagicMock(message_id=next(counter), chat=MagicMock(id=chat_id))

    return MagicMock(send_message=AsyncMock(side_effect=_send), edit_message_text=AsyncMock(),
                     delete_message=AsyncMock(), reopen_forum_topic=AsyncMock())  # fmt: skip


@pytest.fixture
def app():
    return MagicMock(failed_step=AsyncMock(return_value="gate · mypy"), rerun_failed=AsyncMock())


async def _topic(level="all"):
    cfg = await store.repo(REPO)
    topic = await store.save_topic(FORUM, 7, "Zebaro Core")
    await store.set_topic(cfg.id, topic.id)
    await store.set_level(cfg.id, level)


def _run(**over: Any) -> Run:
    base: dict[str, Any] = {"repo": REPO, "workflow": "CI", "run_id": 9, "sha": "abc", "ref": "main", "tag": False,
            "default_branch": True, "status": "completed", "conclusion": "success", "title": "feat: b",
            "url": "https://github.com/run/9", "seconds": 83}  # fmt: skip
    base.update(over)
    return Run(**base)


PUSH = Push(REPO, "main", "abc", "feat: b", 2, "https://github.com/c/abc")


def _sent(bot, chat):
    return [c for c in bot.send_message.await_args_list if c.args[0] == chat]


@pytest.mark.asyncio
async def test_a_push_and_its_ci_are_one_quiet_forum_message(db, settings, bot, app):
    await _topic()
    await delivery.handle(bot, app, PUSH)
    await delivery.handle(bot, app, _run(status="in_progress", conclusion=None, seconds=None))
    await delivery.handle(bot, app, _run())

    [send] = _sent(bot, FORUM)
    assert send.kwargs["message_thread_id"] == 7 and send.kwargs["disable_notification"] is True
    assert "reply_markup" not in send.kwargs
    last = bot.edit_message_text.await_args.args[0]
    assert last.startswith("✅ <b>Zebaro-Core-MCP</b> · main") and "(+1)" in last and "1м 23с" in last
    assert _sent(bot, ADMIN) == []


@pytest.mark.asyncio
async def test_a_failure_on_main_is_loud_in_the_owners_chat_with_buttons(db, settings, bot, app):
    await _topic()
    await delivery.handle(bot, app, _run(conclusion="failure"))

    [dm] = _sent(bot, ADMIN)
    assert dm.kwargs["disable_notification"] is False
    assert "CI упал" in dm.args[1] and "gate · mypy" in dm.args[1]
    buttons = [b.text for b in dm.kwargs["reply_markup"].inline_keyboard[0]]
    assert buttons == ["Логи", "🔁 Перезапустить"]
    [forum] = _sent(bot, FORUM)
    assert forum.args[1].startswith("❌") and "reply_markup" not in forum.kwargs


@pytest.mark.asyncio
async def test_green_again_edits_the_failure_into_fixed_and_the_sweep_removes_it(db, settings, bot, app, mocker):
    await delivery.handle(bot, app, _run(conclusion="failure"))
    await delivery.handle(bot, app, _run(sha="def"))

    fixed = [c for c in bot.edit_message_text.await_args_list if c.kwargs.get("chat_id") == ADMIN]
    assert len(fixed) == 1 and "снова зелёный" in fixed[0].args[0]
    assert await store.live(f"dm:{REPO}:main:CI") is None

    await delivery.github_sweep(bot)
    bot.delete_message.assert_not_awaited()  # not an hour yet
    mocker.patch.object(delivery.time, "time", return_value=delivery.time.time() + delivery.FIXED_KEEP + 1)
    await delivery.github_sweep(bot)
    assert bot.delete_message.await_args.kwargs["chat_id"] == ADMIN


@pytest.mark.asyncio
async def test_a_failure_step_lookup_that_breaks_still_sends_the_failure(db, settings, bot, app):
    app.failed_step.side_effect = httpx.ConnectTimeout("slow")
    await delivery.handle(bot, app, _run(conclusion="failure"))
    assert len(_sent(bot, ADMIN)) == 1


@pytest.mark.asyncio
async def test_a_topic_moved_to_another_forum_gets_a_new_message(db, settings, bot, app):
    await _topic()
    await delivery.handle(bot, app, PUSH)
    cfg = await store.repo(REPO)
    other = await store.save_topic(-200, 3, "Other forum")
    await store.set_topic(cfg.id, other.id)

    await delivery.handle(bot, app, _run())

    assert len(_sent(bot, -200)) == 1
    assert all(c.kwargs.get("chat_id") != -200 for c in bot.edit_message_text.await_args_list)


@pytest.mark.asyncio
async def test_a_flood_of_outside_issues_is_capped_in_the_owners_chat(db, settings, bot, app, mocker):
    mocker.patch.dict(delivery._outside, clear=True)
    for n in range(8):
        await delivery.handle(bot, app, Outside(REPO, "issue", "spam", f"#{n}", "https://github.com/i/1", False))
    dms = _sent(bot, ADMIN)
    assert len(dms) == delivery.OUTSIDE_LIMIT + 1
    assert "слишком много" in dms[-1].args[1] and dms[-1].kwargs["disable_notification"] is True


@pytest.mark.asyncio
async def test_a_repo_without_a_topic_still_reports_failures(db, settings, bot, app):
    await delivery.handle(bot, app, PUSH)
    await delivery.handle(bot, app, _run(conclusion="failure"))

    assert _sent(bot, FORUM) == []
    assert len(_sent(bot, ADMIN)) == 1


@pytest.mark.asyncio
async def test_off_means_nothing_at_all(db, settings, bot, app):
    await _topic(level="off")
    await delivery.handle(bot, app, _run(conclusion="failure"))
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_fails_level_shows_only_what_failed(db, settings, bot, app):
    await _topic(level="fails")
    await delivery.handle(bot, app, PUSH)
    await delivery.handle(bot, app, _run())
    assert _sent(bot, FORUM) == []

    await delivery.handle(bot, app, _run(sha="bad", conclusion="failure"))
    assert len(_sent(bot, FORUM)) == 1


@pytest.mark.asyncio
async def test_a_release_is_one_message_with_its_note(db, settings, bot, app):
    await _topic()
    tag = {"workflow": "CD", "ref": "v0.13.1", "tag": True, "default_branch": False}
    await delivery.handle(bot, app, _run(status="in_progress", conclusion=None, seconds=None, **tag))
    await delivery.handle(bot, app, _run(seconds=130, **tag))
    await delivery.handle(bot, app, Release(REPO, "v0.13.1", "https://github.com/r/1", "Code got simpler."))

    assert len(_sent(bot, FORUM)) == 1
    last = bot.edit_message_text.await_args.args[0]
    assert "Zebaro-Core-MCP v0.13.1" in last and "на проде ✅ 2м 10с" in last and "Code got simpler." in last


@pytest.mark.asyncio
async def test_a_deleted_topic_is_reported_once_with_a_way_out(db, settings, bot, app):
    await _topic()

    async def _send(chat_id, text, **kwargs):
        if chat_id == FORUM:
            raise TelegramBadRequest(SendMessage(chat_id=chat_id, text=text), "Bad Request: message thread not found")
        return MagicMock(message_id=1, chat=MagicMock(id=chat_id))

    bot.send_message.side_effect = _send
    await delivery.handle(bot, app, PUSH)
    await delivery.handle(bot, app, Push(REPO, "main", "xyz", "next", 1, ""))

    [dm] = _sent(bot, ADMIN)
    assert "Zebaro Core" in dm.args[1]
    assert [b.text for b in dm.kwargs["reply_markup"].inline_keyboard[0]] == ["Создать заново", "Выбрать другую"]


@pytest.mark.asyncio
async def test_someone_elses_issue_goes_to_the_forum_and_to_the_owner(db, settings, bot, app):
    await _topic()
    await delivery.handle(bot, app, Outside(REPO, "issue", "alice", "Crash <script>", "https://github.com/i/1", False))

    assert len(_sent(bot, FORUM)) == 1 and len(_sent(bot, ADMIN)) == 1
    assert "&lt;script&gt;" in _sent(bot, ADMIN)[0].args[1]


@pytest.mark.asyncio
async def test_a_security_alert_goes_only_to_the_owner(db, settings, bot, app):
    await _topic()
    await delivery.handle(bot, app, Alert(REPO, "high", "httpx", "SSRF", "https://github.com/a/1"))
    assert _sent(bot, FORUM) == [] and len(_sent(bot, ADMIN)) == 1


# ── the webhook ────────────────────────────────────────────────────────────────


@pytest.fixture
def service(mocker):
    svc = MagicMock(spec=GithubService)
    manager = MagicMock(all_services={"github": svc}, is_service_enabled=MagicMock(return_value=True))
    mocker.patch.object(route.ServiceManager, "get_instance", return_value=manager)
    return svc


async def _post(body: bytes, signature: str | None, delivery_id="d1"):
    api = FastAPI()
    api.include_router(route.router, prefix="/webhook/github")
    headers = {"X-GitHub-Event": "push", "X-GitHub-Delivery": delivery_id}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="https://bot.zebaro.dev") as c:
        return (await c.post("/webhook/github", content=body, headers=headers)).status_code


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


BODY = json.dumps({"repository": {"full_name": REPO}}).encode()


@pytest.mark.asyncio
async def test_a_signed_delivery_is_handed_to_the_service(settings, service):
    assert await _post(BODY, _sign(BODY)) == 200
    service.receive.assert_called_once_with("d1", "push", {"repository": {"full_name": REPO}})


@pytest.mark.asyncio
@pytest.mark.parametrize("signature", [None, "", "sha256=00", _sign(BODY, "other")])
async def test_an_unsigned_or_wrongly_signed_delivery_is_refused(settings, service, signature):
    assert await _post(BODY, signature) == 401
    service.receive.assert_not_called()


@pytest.mark.asyncio
async def test_no_secret_closes_the_webhook(settings, service):
    settings.gh_webhook_secret = ""
    assert await _post(BODY, _sign(BODY, "")) == 401


@pytest.mark.asyncio
async def test_an_oversized_body_is_refused_before_it_is_read(settings, service):
    api = FastAPI()
    api.include_router(route.router, prefix="/webhook/github")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="https://bot.zebaro.dev") as c:
        response = await c.post("/webhook/github", content=b"x" * (route.MAX_BODY + 1))
    assert response.status_code == 413
    service.receive.assert_not_called()


@pytest.mark.asyncio
async def test_an_oversized_chunked_body_without_a_length_is_cut_off(settings, service):
    api = FastAPI()
    api.include_router(route.router, prefix="/webhook/github")

    async def chunks():
        for _ in range(6):
            yield b"x" * (1024 * 1024)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="https://bot.zebaro.dev") as c:
        response = await c.post("/webhook/github", content=chunks())
    assert response.status_code == 413
    service.receive.assert_not_called()


@pytest.mark.asyncio
async def test_a_non_ascii_signature_is_a_401_not_a_500(settings, service):
    assert route.signature_ok(BODY, "sha256=ш") is False


@pytest.mark.asyncio
async def test_an_app_without_a_key_refuses_events(settings, service):
    service.ready = False
    assert await _post(BODY, _sign(BODY)) == 503


@pytest.fixture
def owner_settings(mocker):
    from src.services.github import service as service_module

    mocker.patch.object(service_module, "settings", MagicMock(gh_owner="Zebaro24", gh_app_id=0, gh_app_key=""))


OWN_PUSH = {"ref": "refs/heads/main", "commits": [{"id": "a", "message": "m"}],
            "repository": {"full_name": REPO, "owner": {"login": "Zebaro24"}}}  # fmt: skip


@pytest.mark.asyncio
async def test_a_redelivered_event_is_handled_once(owner_settings):
    svc = GithubService(AsyncMock(), app=MagicMock(configured=True))
    assert svc.receive("d1", "push", OWN_PUSH) is True
    assert svc.receive("d1", "push", OWN_PUSH) is False


@pytest.mark.asyncio
async def test_events_of_another_account_are_ignored(owner_settings):
    deliver = AsyncMock()
    svc = GithubService(deliver, app=MagicMock(configured=True))
    stranger = {**OWN_PUSH, "repository": {"full_name": "eve/x", "owner": {"login": "eve"}}}
    other_install = {"action": "added", "repositories_added": [{"full_name": "eve/y"}],
                     "installation": {"account": {"login": "eve"}}}  # fmt: skip
    assert svc.receive("d2", "push", stranger) is False
    assert svc.receive("d3", "installation_repositories", other_install) is False
    deliver.assert_not_awaited()


# ── /github and the forum ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_topic_names_from_telegram_are_escaped():
    topic = store.Topic(1, FORUM, 7, '<a href="https://evil">x</a>')
    for text in (fmt.topic_bound(topic), fmt.topic_recreated(topic), fmt.topic_broken(topic, [REPO])):
        assert "<a href" not in text and "&lt;a href=" in text


@pytest.mark.asyncio
async def test_bind_from_someone_else_is_ignored_silently(db, mocker):
    mocker.patch.object(admin, "settings", MagicMock(telegram_admin_id=ADMIN))
    message = MagicMock(from_user=MagicMock(id=7), message_thread_id=9, chat=MagicMock(id=FORUM))
    message.delete = AsyncMock()
    message.answer = AsyncMock()

    await admin.bind_command(message, MagicMock(args="Hack"))

    assert await store.topics() == []
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_topics_of_a_forum_the_bot_does_not_write_to_are_not_kept(db):
    created = MagicMock(forum_topic_created=MagicMock(name="x"), forum_topic_edited=None, message_thread_id=5,
                        chat=MagicMock(id=-999))  # fmt: skip
    await admin.topic_seen(created)
    assert await store.topics() == []

    await store.save_topic(FORUM, 7, "Zebaro Core")
    created.chat.id = FORUM
    created.forum_topic_created.name = "New one"
    await admin.topic_seen(created)
    assert sorted(t.name for t in await store.topics()) == ["New one", "Zebaro Core"]
