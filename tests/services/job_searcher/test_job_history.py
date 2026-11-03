"""Jobs API part B, stop 2: the owner's journal, the funnel by event, the silence (S3), the backfill."""

import asyncio
import copy
import sys
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from bson import ObjectId

mock_settings = MagicMock()
mock_settings.app_name = "test"
mock_settings.description = ""
mock_settings.version = "0.0.0"
mock_settings.debug = False
mock_settings.jobs_api_token = "api-token"
mock_settings.tz = "Europe/Berlin"
mock_settings.no_response_days = 21

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=mock_settings)
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from fake_jobs import FakeJobs  # noqa: E402  (pytest puts this directory on sys.path)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.db import sql  # noqa: E402
from src.interfaces.webhooks.main import app  # noqa: E402
from src.services.job_searcher import backfill, events, jobs_api, journal, silence, status  # noqa: E402

AUTH = {"Authorization": "Bearer api-token"}
NOW = datetime.utcnow().replace(microsecond=0)
DAY = timedelta(days=1)


@pytest.fixture
def jobs(mocker):
    fake = FakeJobs()
    for module in (jobs_api, status, events, silence, backfill):
        mocker.patch.object(module, "jobs_collection", fake)
    for module in (jobs_api, events, silence, backfill):
        mocker.patch.object(module, "settings", mock_settings)
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", mock_settings)
    mocker.patch("src.interfaces.webhooks.routes.jobs.kick_status_sync")
    return fake


@pytest.fixture
def meta(mocker):
    fake = FakeJobs()
    mocker.patch.object(silence, "meta_collection", fake)
    mocker.patch.object(backfill, "meta_collection", fake)
    return fake


@pytest.fixture
def db(tmp_path, mocker):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'journal.db'}")

    async def create() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(sql.Base.metadata.create_all)

    asyncio.run(create())
    mocker.patch.object(journal, "_open", async_sessionmaker(engine, expire_on_commit=False))
    yield
    asyncio.run(engine.dispose())


def _call(method: str, path: str, json: Any = None, params: dict[str, Any] | None = None) -> httpx.Response:
    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.request(method, path, json=json, params=params, headers=AUTH)

    return asyncio.run(call())


def _doc(jobs: FakeJobs, **fields: Any) -> dict[str, Any]:
    doc = {
        "_id": ObjectId(),
        "platform_name": "Dou",
        "title": "Python Developer",
        "company": "Acme",
        "found_at": NOW - 60 * DAY,
        "moderation": "sent",
        "user_status": "pending",
        **fields,
    }
    jobs.docs.append(doc)
    return doc


def _read(jobs: FakeJobs, doc: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(jobs.by_id(doc["_id"]))


async def _move(jobs: FakeJobs, doc: dict[str, Any], to: str, at: datetime | None, **extra: Any) -> dict[str, Any]:
    """One change through the real write path; at=None — "no date", an approximate one."""
    current = jobs_api.public_status(_read(jobs, doc))
    extra.setdefault("actor", "ai")
    written = await status.write_status(
        _read(jobs, doc), to, expected=current, occurred_at=at, approximate=at is None, **extra
    )
    assert written.event is not None
    return written.event


def _event_funnel(**params: Any) -> dict[str, Any]:
    params = {"by": "event", "from": (NOW - 30 * DAY).isoformat(), "to": (NOW + DAY).isoformat(), **params}
    response = _call("GET", "/jobs/funnel", params=params)
    assert response.status_code == 200, response.json()
    body: dict[str, Any] = response.json()
    return body


# --- the journal ----------------------------------------------------------------------------------


def test_a_journal_entry_is_stored_and_listed_by_its_time(db, jobs):
    week_ago = (NOW - 7 * DAY).isoformat()
    created = _call(
        "POST", "/jobs/journal", {"kind": "cv", "text": "Новое CV: AI-проекты наверх", "occurred_at": week_ago}
    )
    _call(
        "POST",
        "/jobs/journal",
        {"kind": "letter", "text": "Короче письмо", "occurred_at": (NOW - 40 * DAY).isoformat()},
    )

    assert created.status_code == 201
    assert created.json()["kind"] == "cv" and created.json()["actor"] == "user"
    items = _call("GET", "/jobs/journal").json()["items"]  # the last 30 days
    assert [item["text"] for item in items] == ["Новое CV: AI-проекты наверх"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"kind": "haircut", "text": "x"}, "kind"),
        ({"kind": "cv", "text": "  "}, "text"),
        ({"kind": "cv", "text": "x", "actor": "system"}, "actor"),
        ({"kind": "cv", "text": "x", "occurred_at": "2999-01-01"}, "occurred_at"),
    ],
)
def test_a_bad_journal_entry_is_refused(db, jobs, body, field):
    response = _call("POST", "/jobs/journal", body)

    assert response.status_code == 400 and response.json()["error"]["message"].startswith(field)


def test_the_funnel_carries_the_journal_of_its_period(db, jobs):
    _call(
        "POST",
        "/jobs/journal",
        {"kind": "strategy", "text": "Только AI-вакансии", "occurred_at": (NOW - 3 * DAY).isoformat()},
    )

    body = _event_funnel()
    found = _call("GET", "/jobs/funnel", params={"from": (NOW - 30 * DAY).isoformat()}).json()

    assert [entry["text"] for entry in body["journal"]] == ["Только AI-вакансии"]
    assert found["by"] == "found" and len(found["journal"]) == 1


# --- the funnel by event ------------------------------------------------------------------------------


@pytest.fixture
def no_journal(mocker):
    mocker.patch.object(journal, "entries", new=AsyncMock(return_value=[]))


@pytest.mark.asyncio
async def test_time_to_reply_goes_by_when_it_happened_not_when_it_was_written(jobs, no_journal):
    doc = _doc(jobs)
    await _move(jobs, doc, "applied", NOW - 5 * DAY, actor="user")
    await _move(jobs, doc, "replied", NOW - 3 * DAY, evidence="gmail:1")  # written now, happened 3 days ago

    group = (await asyncio.to_thread(_event_funnel))["groups"][0]

    assert group["time_to_reply"] == {"count": 1, "median_hours": 48.0, "p75_hours": 48.0}
    assert group["entered"]["replied"] == 1 and group["reached"]["replied"] == 1


@pytest.mark.asyncio
async def test_guessed_times_and_silence_are_no_reply_time(jobs, no_journal):
    guessed = _doc(jobs)
    await _move(jobs, guessed, "applied", NOW - 5 * DAY, actor="user")
    await _move(jobs, guessed, "replied", None, evidence="gmail:2")  # no date: approximate
    silent = _doc(jobs)
    await _move(jobs, silent, "applied", NOW - 25 * DAY, actor="user")
    await _move(jobs, silent, "rejected_by_employer", NOW - 2 * DAY, actor="system", reason_code="no_response")

    group = (await asyncio.to_thread(_event_funnel))["groups"][0]

    assert group["time_to_reply"]["count"] == 0
    assert group["rejections"] == {"applied": {"no_response": 1}}
    # Silence is no answer: of the two applications only the guessed reply got one.
    assert group["reached"]["replied"] == 1 and group["reply_rate"] == 0.5


@pytest.mark.asyncio
async def test_silence_is_no_reply_in_the_found_funnel_either(jobs, no_journal):
    doc = _doc(jobs, found_at=NOW - 40 * DAY)
    await _move(jobs, doc, "applied", NOW - 39 * DAY, actor="user")
    await _move(jobs, doc, "rejected_by_employer", NOW - 18 * DAY, actor="system", reason_code="no_response")

    params = {"from": (NOW - 50 * DAY).isoformat()}
    group = (await asyncio.to_thread(_call, "GET", "/jobs/funnel", None, params)).json()["groups"][0]

    assert group["reached"]["applied"] == 1 and group["reached"]["replied"] == 0 and group["reply_rate"] == 0


def test_the_funnel_answers_without_the_journal_when_sql_is_down(jobs, mocker):
    from sqlalchemy.exc import OperationalError

    mocker.patch.object(journal, "entries", new=AsyncMock(side_effect=OperationalError("SELECT", {}, Exception("x"))))

    response = _call("GET", "/jobs/funnel", params={"by": "event"})

    assert response.status_code == 200 and response.json()["journal"] == []


@pytest.mark.asyncio
async def test_a_change_and_its_undo_leave_no_trace_in_the_numbers(jobs, no_journal):
    doc = _doc(jobs)
    await _move(jobs, doc, "applied", NOW - 5 * DAY, actor="user")
    mistake = await _move(jobs, doc, "rejected_by_employer", NOW - 2 * DAY, evidence="gmail:3", reason_code="salary")
    await status.undo(str(doc["_id"]), mistake["id"])
    waiting = _doc(jobs)
    test_patch = await _move(jobs, waiting, "replied", NOW - DAY, evidence="live-check")  # a test PATCH
    await status.undo(str(waiting["_id"]), test_patch["id"])

    group = (await asyncio.to_thread(_event_funnel))["groups"][0]

    assert group["events"] == 1  # only the application
    assert group["entered"]["rejected_by_employer"] == 0 and group["entered"]["replied"] == 0
    assert group["rejections"] == {} and group["time_to_reply"]["count"] == 0
    assert group["transitions"] == [{"from": "new", "to": "applied", "count": 1}]
    assert group["reached"] == {"applied": 1, "replied": 0, "interview": 0, "offer": 0}


@pytest.mark.asyncio
async def test_refusals_are_counted_by_stage_and_reason(jobs, no_journal):
    for stage in ("applied", "interview"):
        doc = _doc(jobs)
        await _move(jobs, doc, "applied", NOW - 9 * DAY, actor="user")
        if stage == "interview":
            await _move(jobs, doc, "interview", NOW - 6 * DAY, evidence="gmail:4")
        await _move(jobs, doc, "rejected_by_employer", NOW - 3 * DAY, evidence="gmail:5", reason_code="experience")

    group = (await asyncio.to_thread(_event_funnel))["groups"][0]

    assert group["rejections"] == {"applied": {"experience": 1}, "interview": {"experience": 1}}
    assert group["reached"]["interview"] == 1 and group["interview_rate"] == 0.5


@pytest.mark.asyncio
async def test_events_outside_the_period_are_not_counted(jobs, no_journal):
    doc = _doc(jobs, found_at=NOW - 90 * DAY)
    await _move(jobs, doc, "applied", NOW - 80 * DAY, actor="user")

    body = await asyncio.to_thread(_event_funnel)

    assert body["by"] == "event" and body["groups"][0]["events"] == 0


def test_percentile_interpolates_between_ranks():
    assert events.percentile([1, 2, 3, 4], 0.75) == 3.25
    assert events.percentile([10], 0.75) == 10


# --- the silence (S3) -----------------------------------------------------------------------------------


async def _applied_days_ago(jobs: FakeJobs, days: int) -> dict[str, Any]:
    doc = _doc(jobs)
    await _move(jobs, doc, "applied", NOW - days * DAY, actor="user")
    return doc


@pytest.mark.asyncio
async def test_21_days_without_an_event_is_no_response_and_20_is_not(jobs, meta):
    old = await _applied_days_ago(jobs, 21)
    fresh = await _applied_days_ago(jobs, 20)
    await meta.update_one({"_id": silence.BACKFILL_ID}, {"$set": {"done_at": NOW}}, upsert=True)

    assert await silence.silence_job() == 1

    stored = jobs.by_id(old["_id"])
    assert jobs_api.public_status(stored) == "rejected_by_employer" and stored["status_reason"] == "no_response"
    assert stored["history"][-1]["actor"] == "system"
    assert jobs_api.public_status(jobs.by_id(fresh["_id"])) == "applied"


@pytest.mark.asyncio
async def test_the_daily_check_waits_for_the_backfill(jobs, meta):
    old = await _applied_days_ago(jobs, 30)

    assert await silence.silence_job() == 0
    assert jobs_api.public_status(jobs.by_id(old["_id"])) == "applied"


# --- the backfill -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_vacancy_without_history_gets_its_chain_from_the_stored_dates(jobs, meta):
    doc = _doc(
        jobs, user_status="applied", outcome="interview",
        status_updated_at=NOW - 10 * DAY, outcome_at=NOW - 4 * DAY,
    )  # fmt: skip

    await backfill.restore(apply=True, now=NOW)

    history = jobs.by_id(doc["_id"])["history"]
    assert [(e["from"], e["to"], e["occurred_at"]) for e in history] == [
        ("new", "applied", NOW - 10 * DAY),
        ("applied", "interview", NOW - 4 * DAY),
    ]
    assert all(e["approximate"] and e["actor"] == "system" and e["restored"] for e in history)


@pytest.mark.asyncio
async def test_restored_events_go_before_the_real_ones_and_join_them(jobs, meta):
    # Applied before the release (no history), then the AI's refusal after it.
    doc = _doc(jobs, user_status="applied", status_updated_at=NOW - 12 * DAY)
    real = await _move(jobs, doc, "rejected_by_employer", NOW - 2 * DAY, evidence="gmail:6", reason_code="salary")

    await backfill.restore(apply=True, now=NOW)

    history = jobs.by_id(doc["_id"])["history"]
    assert [(e["from"], e["to"]) for e in history] == [("new", "applied"), ("applied", "rejected_by_employer")]
    restored, kept = history
    assert restored["to"] == kept["from"] and kept["id"] == real["id"]
    assert restored["approximate"] is True and restored["occurred_at"] == NOW - 12 * DAY
    assert restored["occurred_at"] <= kept["occurred_at"]


@pytest.mark.asyncio
async def test_a_date_moved_by_a_later_write_is_not_trusted(jobs, meta):
    # "Не прохожу" before the release, "Откликнулся" after: status_updated_at is the new one now.
    doc = _doc(jobs, user_status="mismatch", status_reason="english", status_updated_at=NOW - 20 * DAY)
    await _move(jobs, doc, "applied", NOW - DAY, actor="user")

    await backfill.restore(apply=True, now=NOW)

    restored = jobs.by_id(doc["_id"])["history"][0]
    assert (restored["to"], restored["reason_code"]) == ("mismatch", "english")
    assert restored["occurred_at"] == doc["found_at"]  # status_updated_at moved past the real event


@pytest.mark.asyncio
async def test_a_second_backfill_adds_nothing(jobs, meta):
    _doc(jobs, user_status="not_interested", status_reason="role", status_updated_at=NOW - 5 * DAY)
    _doc(jobs, user_status="applied", status_updated_at=NOW - 30 * DAY)

    first = await backfill.restore(apply=True, now=NOW)
    second = await backfill.restore(apply=True, now=NOW)

    assert first["written"] == 2 and second["written"] == 0
    assert all(len(doc["history"]) == 1 for doc in jobs.docs)


@pytest.mark.asyncio
async def test_the_dry_run_writes_nothing_and_counts_the_silence(jobs, meta, capsys):
    _doc(jobs, user_status="applied", status_updated_at=NOW - 30 * DAY)
    _doc(jobs, user_status="applied", status_updated_at=NOW - 5 * DAY)

    await backfill.run(apply=False)

    assert "history" not in jobs.docs[0] and meta.docs == []
    assert "silence: 1 applications" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_the_backfill_turns_old_silence_down_without_telegram_and_opens_the_daily_check(jobs, meta):
    old = _doc(jobs, user_status="applied", status_updated_at=NOW - 30 * DAY, tg_chat_id=1, tg_message_id=10)
    recent = _doc(jobs, user_status="applied", status_updated_at=NOW - 5 * DAY)

    await backfill.run(apply=True)

    stored = jobs.by_id(old["_id"])
    assert stored["status_reason"] == "no_response" and stored["history"][-1]["approximate"] is True
    # Dated when the silence reached 21 days, not on the day of the backfill.
    assert stored["history"][-1]["occurred_at"] == NOW - 30 * DAY + 21 * DAY
    assert "tg_sync" not in stored  # no edit, no note
    assert jobs_api.public_status(jobs.by_id(recent["_id"])) == "applied"
    assert await silence.backfill_done()


@pytest.mark.asyncio
async def test_relabel_turns_other_into_the_new_code(jobs, meta):
    doc = _doc(jobs, user_status="applied", status_updated_at=NOW - 9 * DAY)
    await _move(
        jobs, doc, "rejected_by_employer", NOW - DAY, evidence="gmail:7", reason_code="other",
        suggested_code="relocation_required",
    )  # fmt: skip

    assert await backfill.relabel("rejected_by_employer", "relocation_required", "location", apply=False) == 1
    assert jobs.by_id(doc["_id"])["status_reason"] == "other"  # a dry run
    await backfill.relabel("rejected_by_employer", "relocation_required", "location", apply=True)

    stored = jobs.by_id(doc["_id"])
    assert stored["status_reason"] == "location" and stored["history"][-1]["reason_code"] == "location"
    assert stored["history"][-1]["suggested_code"] == "relocation_required"  # what the AI proposed stays


@pytest.mark.asyncio
async def test_the_event_funnel_example_in_the_contract_has_the_real_shape(jobs, db):
    import json
    from pathlib import Path

    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shape(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shape(value[0])] if value else []
        return type(value).__name__

    text = (Path(__file__).resolve().parents[3] / "docs" / "contracts" / "jobs-api.md").read_text(encoding="utf-8")
    section = text[text.index("### `by=event`") :]
    block = section[section.index("```json") + 7 : section.index("```", section.index("```json") + 7)]
    example = json.loads(block)
    doc = _doc(jobs)
    await _move(jobs, doc, "applied", NOW - 5 * DAY, actor="user")
    await _move(jobs, doc, "replied", NOW - 3 * DAY, evidence="gmail:8")
    await asyncio.to_thread(
        _call, "POST", "/jobs/journal", {"kind": "cv", "text": "CV", "occurred_at": (NOW - DAY).isoformat()}
    )

    real = await asyncio.to_thread(_event_funnel)

    # Counts are ints, rates and hours floats: the example's numbers stand for the same types.
    group, example_group = real["groups"][0], example["groups"][0]
    assert set(group) == set(example_group) and set(group["time_to_reply"]) == set(example_group["time_to_reply"])
    assert shape(real["journal"]) == shape(example["journal"])
    assert set(real) == set(example)
