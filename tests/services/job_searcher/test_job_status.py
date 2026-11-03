"""Jobs API part B: PATCH /jobs/{id}/status, GET /jobs/reasons, history, undo, the Telegram sync."""

import asyncio
import copy
import sys
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from bson import ObjectId

mock_settings = MagicMock()
mock_settings.app_name = "test"
mock_settings.description = ""
mock_settings.version = "0.0.0"
mock_settings.debug = False
mock_settings.telegram_docker_access_ids = [123]
mock_settings.telegram_admin_id = 777
mock_settings.jobs_api_token = "api-token"
mock_settings.tz = "Europe/Berlin"
mock_settings.webhook_url = "https://bot.example"

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=mock_settings)
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from fake_jobs import FakeJobs  # noqa: E402  (pytest puts this directory on sys.path)

from src.interfaces.tg.notification import job_status as sync  # noqa: E402
from src.interfaces.webhooks.main import app  # noqa: E402
from src.services.job_searcher import jobs_api, status  # noqa: E402

AUTH = {"Authorization": "Bearer api-token"}
EVIDENCE = "gmail:18c2f0a1b2"


@pytest.fixture
def jobs(mocker):
    fake = FakeJobs()
    for module in (jobs_api, status, sync):
        mocker.patch.object(module, "jobs_collection", fake)
    mocker.patch.object(jobs_api, "settings", mock_settings)
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", mock_settings)
    mocker.patch("src.interfaces.tg.formatters.job_status.settings", mock_settings)
    mocker.patch("src.interfaces.tg.keyboards.job.settings", mock_settings)
    mocker.patch.object(sync, "settings", mock_settings)
    return fake


@pytest.fixture
def kick(mocker):
    return mocker.patch("src.interfaces.webhooks.routes.jobs.kick_status_sync")


def _call(method: str, path: str, json: dict[str, Any] | None = None) -> httpx.Response:
    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.request(method, path, json=json, headers=AUTH)

    return asyncio.run(call())


def _doc(jobs: FakeJobs, **fields: Any) -> dict[str, Any]:
    doc = {
        "_id": ObjectId(),
        "platform_name": "Dou",
        "title": "Python Developer",
        "company": "Acme",
        "link": "https://jobs.dou.ua/companies/acme/vacancies/1/",
        "found_at": datetime.utcnow() - timedelta(days=10),
        "moderation": "sent",
        "user_status": "pending",
        **fields,
    }
    jobs.docs.append(doc)
    return doc


def _read(jobs: FakeJobs, doc: dict[str, Any]) -> dict[str, Any]:
    """The document as a read returns it: a copy, as MongoDB's is (the fake changes its own in place)."""
    return copy.deepcopy(jobs.by_id(doc["_id"]))


def _applied(jobs: FakeJobs, **fields: Any) -> dict[str, Any]:
    return _doc(jobs, user_status="applied", status_updated_at=datetime.utcnow() - timedelta(days=9), **fields)


def _patch(doc: dict[str, Any], **body: Any) -> httpx.Response:
    return _call("PATCH", f"/jobs/{doc['_id']}/status", body)


def _reject(doc: dict[str, Any], **extra: Any) -> httpx.Response:
    body = {"status": "rejected_by_employer", "expected_status": "applied", "actor": "ai", "evidence": EVIDENCE}
    return _patch(doc, **{**body, **extra})


# --- PATCH ----------------------------------------------------------------------------------------


def test_a_change_is_stored_with_its_event(jobs, kick):
    doc = _applied(jobs, tg_chat_id=1, tg_message_id=10)

    response = _reject(doc, reason_code="salary", reason="Хотят до $1500")

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True and body["telegram"] == "queued"
    assert body["job"]["status"] == "rejected_by_employer"
    assert body["job"]["status_reason_code"] == "salary" and body["job"]["status_reason"] == "Хотят до $1500"
    event = body["job"]["history"][-1]
    assert (event["from"], event["to"], event["actor"], event["reason_code"]) == (
        "applied", "rejected_by_employer", "ai", "salary",
    )  # fmt: skip
    assert event["evidence"] == EVIDENCE and event["approximate"] is True  # no occurred_at sent
    stored = jobs.by_id(doc["_id"])
    # The fields the digest, dedup and the buttons read follow the public status.
    assert (stored["user_status"], stored["outcome"], stored["status_reason"]) == ("applied", "rejected", "salary")
    assert stored["tg_sync"]["state"] == "pending" and stored["tg_sync"]["notify"] is True
    kick.assert_called_once()


def test_the_same_status_and_reason_again_is_no_new_event(jobs, kick):
    doc = _applied(jobs)
    _reject(doc, reason_code="salary")

    # A retry after a lost answer: the client still believes the status is "applied".
    response = _reject(doc, reason_code="salary")

    assert response.status_code == 200 and response.json()["changed"] is False
    assert len(jobs.by_id(doc["_id"])["history"]) == 1


def test_a_new_reason_for_the_same_status_is_a_new_event(jobs, kick):
    doc = _applied(jobs)
    _reject(doc, reason_code="no_reason")

    response = _reject(doc, expected_status="rejected_by_employer", reason_code="experience")

    assert response.json()["changed"] is True
    history = jobs.by_id(doc["_id"])["history"]
    assert [event["reason_code"] for event in history] == ["no_reason", "experience"]


def test_omitted_reason_fields_keep_the_current_ones_on_the_same_status(jobs, kick):
    doc = _applied(jobs)
    _reject(doc, reason_code="salary", reason="до $1500")

    response = _reject(doc, expected_status="rejected_by_employer")

    assert response.json()["changed"] is False
    assert jobs.by_id(doc["_id"])["status_reason_text"] == "до $1500"


def test_a_status_changed_meanwhile_is_a_conflict(jobs, kick):
    doc = _applied(jobs, outcome="interview")

    response = _reject(doc)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "status_conflict" and error["current_status"] == "interview"
    assert "history" not in jobs.by_id(doc["_id"])


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"evidence": None}, "evidence"),  # ai without evidence
        ({"reason_code": "too_expensive"}, "reason_code"),
        ({"reason_code": "other"}, "suggested_code"),
        ({"reason_code": "other", "suggested_code": "Bad Code"}, "suggested_code"),
        ({"reason_code": "salary", "suggested_code": "budget"}, "suggested_code"),
        ({"status": "interview", "reason_code": "salary"}, "reason_code"),  # interview takes no code
        ({"status": "not_interested", "reason_code": "muted"}, "reason_code"),  # a button only
        ({"status": "blocked"}, "status"),
        ({"status": "duplicate"}, "status"),
        ({"actor": "system"}, "actor"),
        ({"expected_status": "pending"}, "expected_status"),
        ({"occurred_at": "2999-01-01"}, "occurred_at"),
        ({"occurred_at": "2020-01-01"}, "occurred_at"),  # before the vacancy was found
        ({"reason_cod": "salary"}, "reason_cod"),  # a typo is refused, not ignored
    ],
)
def test_a_bad_change_is_refused_and_names_the_field(jobs, kick, body, field):
    doc = _applied(jobs)

    response = _reject(doc, **body)

    assert response.status_code == 400, response.json()
    error = response.json()["error"]
    assert error["code"] == "invalid_parameter" and error["message"].startswith(field)
    assert "history" not in jobs.by_id(doc["_id"])


def test_other_with_a_suggested_code_is_taken(jobs, kick):
    doc = _applied(jobs)

    response = _reject(doc, reason_code="other", suggested_code="relocation_required", reason="Только с релокацией")

    assert response.status_code == 200
    assert response.json()["job"]["history"][-1]["suggested_code"] == "relocation_required"


def test_occurred_at_is_the_events_time_and_not_a_guess(jobs, kick):
    doc = _applied(jobs)
    when = datetime.utcnow() - timedelta(days=3)

    event = _reject(doc, occurred_at=when.isoformat() + "Z").json()["job"]["history"][-1]

    assert event["occurred_at"] == jobs_api.utc(when) and event["approximate"] is False
    assert event["recorded_at"] != event["occurred_at"]


def test_a_repeat_points_to_the_copy_with_the_decision(jobs, kick):
    root = _applied(jobs)
    doc = _doc(jobs, user_status="duplicate", group_id=str(root["_id"]))

    response = _patch(doc, status="not_interested", expected_status="duplicate", actor="user")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "is_duplicate", "message": response.json()["error"]["message"], "duplicate_of": str(root["_id"]),
    }  # fmt: skip


def test_a_decision_closes_the_copies_still_waiting(jobs, kick):
    doc = _doc(jobs)
    waiting = _doc(jobs, platform_name="Djinni", group_id=str(doc["_id"]))

    response = _patch(doc, status="applied", expected_status="new", actor="user")

    event_id = response.json()["job"]["history"][-1]["id"]
    copy = jobs.by_id(waiting["_id"])
    assert copy["user_status"] == "duplicate"
    assert copy["history"][-1]["actor"] == "system" and copy["history"][-1]["cause"] == event_id


def test_a_user_change_without_a_message_has_nothing_for_telegram(jobs, kick):
    doc = _doc(jobs)

    body = _patch(doc, status="mismatch", expected_status="new", actor="user", reason_code="english").json()

    assert body["telegram"] == "skipped" and "tg_sync" not in jobs.by_id(doc["_id"])
    kick.assert_not_called()


def test_an_unknown_vacancy_is_404(jobs, kick):
    response = _call(
        "PATCH", f"/jobs/{ObjectId()}/status", {"status": "applied", "expected_status": "new", "actor": "user"}
    )

    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_the_reasons_are_listed_per_status(jobs):
    statuses = _call("GET", "/jobs/reasons").json()["statuses"]

    employer = [reason["code"] for reason in statuses["rejected_by_employer"]]
    assert {"no_reason", "work_permit", "location", "no_response", "other"} <= set(employer)
    assert "muted" not in [reason["code"] for reason in statuses["not_interested"]]
    assert all(reason["description"] for codes in statuses.values() for reason in codes)


def test_one_vacancy_without_history_keeps_its_part_a_answer(jobs):
    doc = _doc(
        jobs, user_status="applied", status_updated_at=datetime(2026, 10, 19), outcome="reply",
        outcome_at=datetime(2026, 10, 20, 9, 0),
    )  # fmt: skip

    body = _call("GET", f"/jobs/{doc['_id']}").json()

    assert body["history"] == [] and body["status"] == "replied"
    assert body["status_changed_at"] == "2026-10-20T09:00:00Z"


def test_the_event_example_in_the_contract_has_the_real_keys(jobs, kick):
    import json
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "docs" / "contracts" / "jobs-api.md").read_text(encoding="utf-8")
    section = text[text.index("Событие журнала (B):") :]
    block = section[section.index("```json") + 7 : section.index("```", section.index("```json") + 7)]
    doc = _applied(jobs)

    event = _reject(doc, reason_code="salary").json()["job"]["history"][-1]

    assert set(event) == set(json.loads(block))


# --- undo -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undo_brings_back_the_status_and_its_reason(jobs):
    doc = _doc(jobs, user_status="mismatch", status_reason="english")
    written = await status.write_status(_read(jobs, doc), "applied", expected="mismatch", actor="ai", evidence=EVIDENCE)

    assert written.event is not None
    await status.undo(str(doc["_id"]), written.event["id"])

    stored = jobs.by_id(doc["_id"])
    assert (stored["user_status"], stored["status_reason"]) == ("mismatch", "english")
    assert stored["history"][-1]["undo_of"] == written.event["id"]


@pytest.mark.asyncio
async def test_undo_reopens_the_copies_the_change_closed(jobs):
    doc = _doc(jobs)
    waiting = _doc(jobs, group_id=str(doc["_id"]))
    written = await status.write_status(_read(jobs, doc), "applied", expected="new", actor="ai", evidence=EVIDENCE)
    assert jobs.by_id(waiting["_id"])["user_status"] == "duplicate"

    assert written.event is not None
    await status.undo(str(doc["_id"]), written.event["id"])

    assert jobs.by_id(doc["_id"])["user_status"] == "pending"
    assert jobs.by_id(waiting["_id"])["user_status"] == "pending"


@pytest.mark.asyncio
async def test_undo_after_a_later_change_changes_nothing(jobs):
    doc = _applied(jobs)
    first = await status.write_status(_read(jobs, doc), "replied", expected="applied", actor="ai")
    await status.write_status(_read(jobs, doc), "interview", expected="replied", actor="user")

    assert first.event is not None
    with pytest.raises(status.StatusConflict):
        await status.undo(str(doc["_id"]), first.event["id"])
    assert jobs_api.public_status(jobs.by_id(doc["_id"])) == "interview"


# --- the Telegram sync ------------------------------------------------------------------------------


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


async def _ai_change(jobs: FakeJobs, to: str = "rejected_by_employer", **fields: Any) -> dict[str, Any]:
    doc = _applied(jobs, **fields)
    await status.write_status(_read(jobs, doc), to, expected="applied", actor="ai", evidence=EVIDENCE, notify=True)
    return jobs.by_id(doc["_id"])


def _error(kind: type[TelegramAPIError], message: str, **extra: Any) -> Exception:
    error: Exception = kind(method=MagicMock(), message=message, **extra)
    return error


@pytest.mark.asyncio
async def test_the_message_is_edited_and_a_quiet_note_answers_it(jobs):
    doc = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10, tg_message_kind="rich")
    bot = _bot()

    assert await sync.sync_job_messages(bot) == 1

    edit = bot.edit_message_text.await_args.kwargs
    assert (edit["chat_id"], edit["message_id"]) == (1, 10)
    assert "🤖" in edit["rich_message"].html and "Отказ" in edit["rich_message"].html
    note = bot.send_message.await_args.kwargs
    assert note["reply_parameters"].message_id == 10 and note["disable_notification"] is True
    assert "↩️ Отменить" in [b.text for row in note["reply_markup"].inline_keyboard for b in row]
    assert jobs.by_id(doc["_id"])["tg_sync"]["state"] == "done"


@pytest.mark.asyncio
async def test_the_edited_message_keeps_the_description(jobs):
    await _ai_change(jobs, tg_chat_id=1, tg_message_id=10, description="Будуємо платформу на FastAPI.")
    bot = _bot()

    await sync.sync_job_messages(bot)

    assert "FastAPI" in bot.edit_message_text.await_args.kwargs["rich_message"].html


@pytest.mark.asyncio
async def test_a_document_that_breaks_the_render_does_not_hold_up_the_rest(jobs, mocker):
    broken = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10)
    fine = await _ai_change(jobs, tg_chat_id=1, tg_message_id=11)
    real = sync.job_status_line

    def line(doc: dict[str, Any]) -> str | None:
        if doc["_id"] == broken["_id"]:
            raise KeyError("an odd legacy field")
        return real(doc)

    mocker.patch.object(sync, "job_status_line", side_effect=line)

    await sync.sync_job_messages(_bot())

    assert jobs.by_id(broken["_id"])["tg_sync"]["attempts"] == 1  # tried again later
    assert jobs.by_id(fine["_id"])["tg_sync"]["state"] == "done"


@pytest.mark.asyncio
async def test_an_interview_rings(jobs):
    await _ai_change(jobs, "interview", tg_chat_id=1, tg_message_id=10)
    bot = _bot()

    await sync.sync_job_messages(bot)

    assert bot.send_message.await_args.kwargs["disable_notification"] is False


@pytest.mark.asyncio
async def test_not_modified_is_success(jobs):
    doc = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10)
    bot = _bot()
    bot.edit_message_text.side_effect = _error(TelegramBadRequest, "Bad Request: message is not modified")

    await sync.sync_job_messages(bot)

    assert jobs.by_id(doc["_id"])["tg_sync"]["state"] == "done"
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_deleted_message_is_gone_and_the_note_comes_on_its_own(jobs):
    doc = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10)
    bot = _bot()
    bot.edit_message_text.side_effect = _error(TelegramBadRequest, "Bad Request: message to edit not found")

    await sync.sync_job_messages(bot)

    assert jobs.by_id(doc["_id"])["tg_sync"]["state"] == "gone"
    note = bot.send_message.await_args.kwargs
    assert note["reply_parameters"] is None
    assert "🔗 Вакансия" in [b.text for row in note["reply_markup"].inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_a_vacancy_without_a_message_still_gets_the_note(jobs):
    await _ai_change(jobs)
    bot = _bot()

    await sync.sync_job_messages(bot)

    bot.edit_message_text.assert_not_awaited()
    assert bot.send_message.await_args.kwargs["chat_id"] == 777


@pytest.mark.asyncio
async def test_flood_control_is_waited_out_and_tried_again(jobs, mocker):
    sleep = mocker.patch.object(sync.asyncio, "sleep", new=AsyncMock())
    doc = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10)
    bot = _bot()
    bot.edit_message_text.side_effect = [_error(TelegramRetryAfter, "Too Many Requests", retry_after=3), True]

    await sync.sync_job_messages(bot)

    sleep.assert_awaited_once_with(3)
    assert bot.edit_message_text.await_count == 2
    assert jobs.by_id(doc["_id"])["tg_sync"]["state"] == "done"


@pytest.mark.asyncio
async def test_telegram_down_keeps_the_status_and_tries_later(jobs):
    doc = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10)
    bot = _bot()
    bot.edit_message_text.side_effect = _error(TelegramNetworkError, "Request timeout error")

    assert await sync.sync_job_messages(bot) == 0

    stored = jobs.by_id(doc["_id"])
    assert jobs_api.public_status(stored) == "rejected_by_employer"  # not taken back
    assert stored["tg_sync"]["state"] == "pending" and stored["tg_sync"]["attempts"] == 1
    assert stored["tg_sync"]["next_at"] > datetime.utcnow()


@pytest.mark.asyncio
async def test_a_pending_change_is_picked_up_by_a_fresh_run(jobs):
    """What a restart leaves: the mark in the document is all a new process needs."""
    doc = await _ai_change(jobs, tg_chat_id=1, tg_message_id=10)
    jobs.by_id(doc["_id"])["tg_sync"]["next_at"] = datetime.utcnow() - timedelta(hours=1)

    assert await sync.sync_job_messages(_bot()) == 1
    assert await sync.sync_job_messages(_bot()) == 0  # and only once


@pytest.mark.asyncio
async def test_no_note_about_a_change_already_overtaken(jobs):
    doc = await _ai_change(jobs, "replied", tg_chat_id=1, tg_message_id=10)
    # The owner pressed a button before the loop ran: no event of its own for Telegram.
    await status.write_status(_read(jobs, doc), "interview", expected="replied", actor="user", sync=False)
    bot = _bot()

    await sync.sync_job_messages(bot)

    bot.edit_message_text.assert_awaited_once()  # the message shows the latest status
    bot.send_message.assert_not_awaited()
