import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())

from src.services.job_searcher import store
from src.services.job_searcher.store import J

T0 = datetime(2026, 11, 1, 10, 0, 0, 583000)
A, B, C = "6a" + "0" * 22, "6b" + "0" * 22, "6c" + "0" * 22


def _doc(job_id: str, **fields):
    return {"_id": job_id, "platform_name": "Dou", "job_id": job_id[:4], "title": "Python", "link": "https://x",
            "found_at": T0, **fields}  # fmt: skip


@pytest.mark.asyncio
async def test_a_document_comes_back_as_it_went_in(sql_db):
    event = {"id": "e1", "occurred_at": T0, "recorded_at": T0, "from": "new", "to": "applied", "actor": "user",
             "reason_code": None, "suggested_code": None, "reason": None, "evidence": None, "approximate": False,
             "from_reason_code": None, "from_reason": None}  # fmt: skip
    note = {"similar_to": B, "similar_to_platform": "Djinni", "similar_seen_at": T0, "similar_clicked": True}
    history = [{"title": "Old", "status": "applied", "at": T0, "platform": "Dou", "similar": True}]
    await store.put([_doc(B), _doc(A, group_id=B, history=[event], company_history=history, warnings=[], **note)])

    doc = await store.get(A)

    assert doc is not None and doc["group_id"] == B and doc["warnings"] == []
    assert doc["history"] == [{**event, "cause": None, "restored": None, "undo_of": None}]
    assert doc["company_history"] == history  # the nested datetime is a datetime again
    assert doc["similar_to_platform"] == "Djinni" and doc["similar_seen_at"] == T0 and doc["similar_status"] is None
    assert doc["tg_sync"] is None and doc["description"] is None


@pytest.mark.asyncio
async def test_null_means_missing_as_in_mongodb(sql_db):
    await store.put([_doc(A, user_status="pending"), _doc(B, user_status=None), _doc(C, user_status="applied")])

    async def found(condition):
        return sorted(d["_id"] for d in await store.find(condition))

    assert await found(store.ne(J.user_status, "applied")) == [A, B]
    assert await found(store.in_(J.user_status, ["pending", None])) == [A, B]
    assert await found(store.not_in(J.user_status, [None, "pending"])) == [C]
    assert await found(store.not_in(J.user_status, ["pending"])) == [B, C]
    assert await found(store.eq(J.user_status, None)) == [B]
    assert await found(store.in_(J.user_status, [])) == []


@pytest.mark.asyncio
async def test_an_update_holds_only_while_its_condition_does_and_events_keep_their_order(sql_db):
    await store.put([_doc(A, user_status="pending")])
    first = {"id": "e1", "from": "new", "to": "applied", "actor": "user"}

    assert await store.update(A, {"user_status": "applied"}, where=J.user_status == "pending", event=first)
    # A second writer that saw "pending" loses: nothing is written, no event.
    assert not await store.update(A, {"user_status": "mismatch"}, where=J.user_status == "pending", event=first)
    assert await store.update(A, {"outcome": "reply"}, event={"id": "e2", "from": "applied", "to": "replied"})

    doc = await store.get(A)
    assert doc is not None and doc["user_status"] == "applied" and doc["outcome"] == "reply"
    assert [e["id"] for e in doc["history"]] == ["e1", "e2"]
    assert await store.count(store.has_event(store.E.id == "e2")) == 1
    assert not await store.update("f" * 24, {"outcome": "offer"})


@pytest.mark.asyncio
async def test_the_note_and_the_outbox_take_their_old_keys(sql_db):
    await store.put([_doc(A, similar_to=B, similar_to_platform="Dou")])

    await store.update(
        A, {"similar_status": "blocked", "tg_sync": {"state": "pending", "event_id": "e1", "next_at": T0}}
    )
    await store.update(A, {"tg_sync.state": "done", "tg_sync.settled_at": T0})

    doc = await store.get(A)
    assert doc is not None and (doc["similar_to"], doc["similar_status"]) == (B, "blocked")  # merged, not replaced
    assert doc["tg_sync"] == {"state": "done", "event_id": "e1", "notify": False, "attempts": 0, "next_at": T0,
                              "settled_at": T0}  # fmt: skip
    with pytest.raises(store.UnknownField):
        await store.update(A, {"no_such_field": 1})


@pytest.mark.asyncio
async def test_a_click_counts_from_nothing(sql_db):
    await store.put([_doc(A)])

    before = await store.increment(A, "click_count")
    await store.increment(A, "click_count")

    assert before is not None and before["click_count"] is None
    assert (await store.get(A) or {})["click_count"] == 2
    assert await store.increment("f" * 24, "click_count") is None
    assert await store.increment("not-an-id", "click_count") is None
