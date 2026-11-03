"""Writing a vacancy's status: one path for the Jobs API, the Telegram buttons and the bot itself.

A change is one `find_one_and_update` that checks the status the writer saw (`expected`), sets
the stored fields the rest of the bot reads (`user_status`, `outcome`, `status_reason`, their
dates) and appends the event to `history` — so the status and its journal never part. Telegram
is told afterwards: `tg_sync` marks the document for the sync loop
(interfaces/tg/notification/job_status.py), and a Telegram failure never takes a status back.

An event's `occurred_at` is when it happened (the e-mail's date); `recorded_at` is when the bot
wrote it. Analytics go by `occurred_at`; events whose time is a guess are `approximate`.
"""

import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from src.db.client import jobs_collection
from src.services.job_searcher.dedup import BLOCKED, DECIDED, DUPLICATE, PENDING, group_root
from src.services.job_searcher.jobs_api import (
    STATUSES,
    InvalidParameter,
    duplicate_targets,
    parse_time,
    public_status,
    status_condition,
)
from src.services.job_searcher.reasons import BUTTON_ONLY, OTHER, REASONS

logger = logging.getLogger("job_searcher.status")

# A client sets any public status but these two: "blocked" is a Telegram button (dedup acts on
# it), "duplicate" is the bot's.
WRITABLE = tuple(status for status in STATUSES if status not in (BLOCKED, DUPLICATE))
ACTORS = ("ai", "user")  # "system" is the bot's own
# The statuses the owner hears about at once; every other change arrives silently.
LOUD = ("replied", "interview", "offer")
_OUTCOMES = {"replied": "reply", "interview": "interview", "offer": "offer", "rejected_by_employer": "rejected"}
# A client's clock may run a little ahead of the server's.
CLOCK_SKEW = timedelta(minutes=5)
MAX_REASON = 2000
MAX_EVIDENCE = 1000
_CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class JobNotFound(LookupError):
    pass


class StatusConflict(Exception):
    """The status is not the one the writer saw."""

    def __init__(self, current_status: str) -> None:
        super().__init__(current_status)
        self.current_status = current_status


class IsDuplicate(Exception):
    """The vacancy is a repeat: its decision lives on another copy."""

    def __init__(self, duplicate_of: str) -> None:
        super().__init__(duplicate_of)
        self.duplicate_of = duplicate_of


@dataclass
class Written:
    changed: bool
    doc: dict[str, Any]
    event: dict[str, Any] | None = None
    queued: bool = False  # Telegram has something to do (tg_sync set)


# --- storage ------------------------------------------------------------------------------------


def storage_fields(status: str, reason_code: str | None, reason: str | None) -> dict[str, Any]:
    """A public status → the stored fields it is made of (the reverse of jobs_api.public_status)."""
    if status == "new":
        user_status, outcome = PENDING, None
    elif status == "applied" or status in _OUTCOMES:
        user_status, outcome = "applied", _OUTCOMES.get(status)
    else:
        user_status, outcome = status, None
    return {"user_status": user_status, "outcome": outcome, "status_reason": reason_code, "status_reason_text": reason}


def _group_query(root: str) -> dict[str, Any]:
    try:
        return {"$or": [{"_id": ObjectId(root)}, {"group_id": root}]}
    except InvalidId:
        return {"group_id": root}


async def group_docs(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every copy of the vacancy (the same vacancy on other sites), this one included."""
    return [copy async for copy in jobs_collection.find(_group_query(group_root(doc)))]


def new_event(
    doc: dict[str, Any],
    to: str,
    *,
    actor: str,
    occurred_at: datetime,
    now: datetime,
    approximate: bool,
    reason_code: str | None = None,
    suggested_code: str | None = None,
    reason: str | None = None,
    evidence: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": secrets.token_hex(6),
        "occurred_at": occurred_at,
        "recorded_at": now,
        "from": public_status(doc),
        "to": to,
        "actor": actor,
        "reason_code": reason_code,
        "suggested_code": suggested_code,
        "reason": reason,
        "evidence": evidence,
        "approximate": approximate,
        # What it replaced, so that "↩️ Отменить" brings the reason back too.
        "from_reason_code": doc.get("status_reason"),
        "from_reason": doc.get("status_reason_text"),
        **{key: value for key, value in extra.items() if value is not None},
    }


def _system_event(doc: dict[str, Any], to: str, now: datetime, **extra: Any) -> dict[str, Any]:
    return new_event(doc, to, actor="system", occurred_at=now, now=now, approximate=False, **extra)


async def write_status(
    doc: dict[str, Any],
    to: str,
    *,
    expected: str,
    actor: str,
    reason_code: str | None = None,
    suggested_code: str | None = None,
    reason: str | None = None,
    evidence: str | None = None,
    occurred_at: datetime | None = None,
    approximate: bool = False,
    notify: bool = False,
    sync: bool = True,
    group: list[dict[str, Any]] | None = None,
    undo_of: str | None = None,
) -> Written:
    """Change the status if it still is `expected`; no checks of the values — callers validate.

    The same status with the same reason is no change and no event. `sync=False` is for a writer
    that shows the change in Telegram itself (a button edits its own message). Raises
    StatusConflict / JobNotFound.
    """
    if public_status(doc) == to and (doc.get("status_reason"), doc.get("status_reason_text")) == (reason_code, reason):
        return Written(changed=False, doc=doc)
    now = datetime.utcnow()
    when = occurred_at or now
    event = new_event(
        doc, to, actor=actor, occurred_at=when, now=now, approximate=approximate, reason_code=reason_code,
        suggested_code=suggested_code, reason=reason, evidence=evidence, undo_of=undo_of,
    )  # fmt: skip
    change = storage_fields(to, reason_code, reason)
    if change["user_status"] != doc.get("user_status"):
        change["status_updated_at"] = when
    if change["outcome"] and change["outcome"] != doc.get("outcome"):
        change["outcome_at"] = when
    queued = sync and (notify or bool(doc.get("tg_message_id")))
    if queued:
        change["tg_sync"] = {
            "state": "pending",
            "event_id": event["id"],
            "notify": notify,
            "attempts": 0,
            "next_at": now,
        }
    after = await jobs_collection.find_one_and_update(
        {"$and": [{"_id": doc["_id"]}, status_condition(expected)]},
        {"$set": change, "$push": {"history": event}},
        return_document=ReturnDocument.AFTER,
    )
    if after is None:
        fresh = await jobs_collection.find_one({"_id": doc["_id"]})
        if fresh is None:
            raise JobNotFound(str(doc["_id"]))
        raise StatusConflict(public_status(fresh))
    if change["user_status"] in DECIDED and doc.get("user_status") not in DECIDED:
        await _close_copies(doc, group if group is not None else await group_docs(doc), event["id"], now)
    logger.info("Job %s: %s → %s by %s", doc["_id"], event["from"], to, actor)
    return Written(changed=True, doc=after, event=event, queued=queued)


async def _close_copies(doc: dict[str, Any], group: list[dict[str, Any]], cause: str, now: datetime) -> None:
    """The copies still waiting in the chat are the same vacancy: answered too, as repeats."""
    waiting = [copy for copy in group if copy["_id"] != doc["_id"] and copy.get("user_status") == PENDING]
    if not waiting:
        return
    await jobs_collection.update_many(
        {"_id": {"$in": [copy["_id"] for copy in waiting]}, "user_status": PENDING},
        {
            "$set": {"user_status": DUPLICATE, "status_updated_at": now},
            "$push": {"history": _system_event(waiting[0], DUPLICATE, now, cause=cause)},
        },
    )


async def undo(job_id: str, event_id: str) -> Written:
    """Take an event back: the status before it, and the copies it turned into repeats.

    Only the vacancy's last event can be undone, and only while the status is still the one it
    set; otherwise StatusConflict — something changed it since.
    """
    doc = await jobs_collection.find_one({"_id": ObjectId(job_id)}) if ObjectId.is_valid(job_id) else None
    if doc is None:
        raise JobNotFound(job_id)
    history = doc.get("history") or []
    event = next((item for item in history if item.get("id") == event_id), None)
    if event is None or history[-1].get("id") != event_id or public_status(doc) != event.get("to"):
        raise StatusConflict(public_status(doc))
    written = await write_status(
        doc, event.get("from") or "new", expected=event["to"], actor="user",
        reason_code=event.get("from_reason_code"), reason=event.get("from_reason"), undo_of=event_id,
    )  # fmt: skip
    now = datetime.utcnow()
    closed = {"$and": [_group_query(group_root(doc)), {"user_status": DUPLICATE, "history.cause": event_id}]}
    reopen = _system_event({"user_status": DUPLICATE}, "new", now, undo_of=event_id)
    try:
        await jobs_collection.update_many(
            closed, {"$set": {"user_status": PENDING, "status_updated_at": now}, "$push": {"history": reopen}}
        )
    except PyMongoError:
        # The status is back already and this event is no longer the last one: say it loudly,
        # the copies have to be reopened by hand (their history names the cause).
        logger.error("Undo of %s on job %s: the copies it closed stay repeats", event_id, job_id, exc_info=True)
    return written


# --- the Jobs API's PATCH -------------------------------------------------------------------------


@dataclass
class StatusChange:
    """The body of PATCH /jobs/{id}/status; `given` names the fields the client sent."""

    status: str
    expected_status: str
    actor: str
    reason_code: str | None = None
    suggested_code: str | None = None
    reason: str | None = None
    evidence: str | None = None
    occurred_at: str | None = None
    given: set[str] = field(default_factory=set)
    inherited_code: bool = False  # the code is the stored one, not the client's: not checked again


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value else None


def validate(change: StatusChange) -> None:
    """Everything that can be checked without the vacancy; InvalidParameter names the field."""
    if change.status not in STATUSES:
        raise InvalidParameter(f"status: unknown value {change.status!r}; one of: {', '.join(WRITABLE)}")
    if change.status not in WRITABLE:
        who = "a Telegram button only" if change.status == BLOCKED else "the bot only"
        raise InvalidParameter(f"status: {change.status!r} is set by {who}; one of: {', '.join(WRITABLE)}")
    if change.expected_status not in STATUSES:
        raise InvalidParameter(
            f"expected_status: unknown value {change.expected_status!r}; one of: {', '.join(STATUSES)}"
        )
    if change.actor not in ACTORS:
        raise InvalidParameter(f"actor: {change.actor!r} is not allowed; one of: {', '.join(ACTORS)}")
    if change.actor == "ai" and not change.evidence:
        raise InvalidParameter("evidence: required when actor is ai — the Gmail message id or a quote of the e-mail")
    if change.reason and len(change.reason) > MAX_REASON:
        raise InvalidParameter(f"reason: {len(change.reason)} characters, at most {MAX_REASON}")
    if change.evidence and len(change.evidence) > MAX_EVIDENCE:
        raise InvalidParameter(f"evidence: {len(change.evidence)} characters, at most {MAX_EVIDENCE}")
    _validate_codes(change)


def _validate_codes(change: StatusChange) -> None:
    if change.inherited_code:  # a "muted" or a since-renamed code stays as it is
        return
    codes = REASONS.get(change.status)
    code, suggested = change.reason_code, change.suggested_code
    if code is not None:
        if codes is None:
            with_codes = ", ".join(REASONS)
            raise InvalidParameter(f"reason_code: status {change.status!r} takes no code (only {with_codes} do)")
        if code in BUTTON_ONLY:
            raise InvalidParameter(f"reason_code: {code!r} is set by a Telegram button only")
        if code not in codes:
            allowed = ", ".join(c for c in codes if c not in BUTTON_ONLY)
            raise InvalidParameter(f"reason_code: unknown code {code!r} for {change.status}; one of: {allowed}")
    if code == OTHER and not suggested:
        raise InvalidParameter(
            "suggested_code: required with reason_code 'other' — the code that would fit, snake_case"
        )
    if suggested is not None:
        if code != OTHER:
            raise InvalidParameter("suggested_code: only with reason_code 'other'")
        if not _CODE.match(suggested):
            raise InvalidParameter(f"suggested_code: {suggested!r} is not snake_case (a-z, 0-9, _), 2–40 characters")
        if codes and suggested in codes:
            raise InvalidParameter(f"suggested_code: {suggested!r} is a known code — send it as reason_code")


def _occurred_at(change: StatusChange, doc: dict[str, Any]) -> datetime | None:
    when = parse_time("occurred_at", change.occurred_at)
    if when is None:
        return None
    if when > datetime.utcnow() + CLOCK_SKEW:
        raise InvalidParameter(f"occurred_at: {change.occurred_at} is in the future")
    found_at = doc.get("found_at")
    if isinstance(found_at, datetime) and when < found_at:
        raise InvalidParameter(
            f"occurred_at: {change.occurred_at} is before the vacancy was found ({found_at:%Y-%m-%d %H:%M}Z)"
        )
    return when


async def patch_status(job_id: str, change: StatusChange) -> Written:
    """PATCH /jobs/{id}/status. Raises InvalidParameter, JobNotFound, IsDuplicate, StatusConflict."""
    change.reason, change.evidence = _clean(change.reason), _clean(change.evidence)
    change.suggested_code = _clean(change.suggested_code)
    doc = await jobs_collection.find_one({"_id": ObjectId(job_id)}) if ObjectId.is_valid(job_id) else None
    if doc is None:
        raise JobNotFound(job_id)
    if public_status(doc) == change.status:
        # The same status: what the client did not send stays as it is (a retry, or a new reason only).
        if "reason_code" not in change.given:
            change.reason_code, change.inherited_code = doc.get("status_reason"), True
            if change.reason_code == OTHER and "suggested_code" not in change.given:
                change.suggested_code = (doc.get("history") or [{}])[-1].get("suggested_code")
        if "reason" not in change.given:
            change.reason = doc.get("status_reason_text")
    validate(change)
    if doc.get("user_status") == DUPLICATE:
        targets = await duplicate_targets([doc])
        raise IsDuplicate(targets.get(job_id) or group_root(doc))
    occurred_at = _occurred_at(change, doc)

    group = None
    to_user_status = storage_fields(change.status, None, None)["user_status"]
    if to_user_status in DECIDED and doc.get("user_status") not in DECIDED:
        group = await group_docs(doc)
        answered = next((d for d in group if d["_id"] != doc["_id"] and d.get("user_status") in DECIDED), None)
        if answered is not None:  # one vacancy, one decision: it is made on the other copy
            raise IsDuplicate(str(answered["_id"]))

    return await write_status(
        doc, change.status, expected=change.expected_status, actor=change.actor,
        reason_code=change.reason_code, suggested_code=change.suggested_code, reason=change.reason,
        evidence=change.evidence, occurred_at=occurred_at, approximate=occurred_at is None,
        notify=change.actor == "ai", group=group,
    )  # fmt: skip
