"""The stored vacancies, read and written as the documents the job searcher works with.

The rest of the job searcher reads a vacancy as one dict — `_id`, its fields, `history` (the events in
order), `tg_sync` (the Telegram outbox) and the `similar_*` note — the shape it had in MongoDB. This module
is the only one that knows the tables behind it (models.py): `to_doc` builds the dict from the rows,
`put` stores one, `update` changes one under a condition and may append an event, in one transaction.

Conditions are SQLAlchemy expressions on `JobRow` (`J`). A null and a missing field were one thing in
MongoDB, and a comparison with NULL is never true in SQL: `ne` / `not_in` keep MongoDB's meaning (a
vacancy without the field differs from any value). `has_event` reaches into the history.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import fields as dataclass_fields
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, delete, exists, func, insert, or_, select, true
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import sql
from src.services.job_searcher.models import JobEvent, JobRow, JobSync

J = JobRow
E = JobEvent

COLUMNS = tuple(c.name for c in J.__table__.columns if c.name not in ("id", "seen_before"))
# The card's "seen before" note: one JSON column, the old keys in the document.
SIMILAR = {"similar_to": "to", "similar_to_platform": "platform", "similar_seen_at": "seen_at",
           "similar_status": "status", "similar_clicked": "clicked"}  # fmt: skip
EVENT_KEYS = {"from": "from_status", "to": "to_status"}
EVENT_COLUMNS = tuple(c.name for c in E.__table__.columns if c.name not in ("job_id", "position"))
SYNC_COLUMNS = tuple(c.name for c in JobSync.__table__.columns if c.name != "job_id")
_ID = re.compile(r"^[0-9a-f]{24}$")


class UnknownField(ValueError):
    """A key no column takes: refused, never dropped."""


def valid_id(job_id: Any) -> bool:
    return isinstance(job_id, str) and _ID.match(job_id) is not None


# --- conditions ----------------------------------------------------------------------------------


def ne(column: Any, value: Any) -> ColumnElement[bool]:
    """MongoDB's {f: {$ne: v}}: a missing field differs too."""
    return column.is_(None) if value is None else or_(column != value, column.is_(None))


def in_(column: Any, values: Iterable[Any]) -> ColumnElement[bool]:
    """MongoDB's {f: {$in: [...]}}, None in the list meaning "missing"."""
    values = list(values)
    real = [v for v in values if v is not None]
    condition: ColumnElement[bool] = column.in_(real)
    if None in values:
        return or_(condition, column.is_(None)) if real else cast(ColumnElement[bool], column.is_(None))
    return condition


def not_in(column: Any, values: Iterable[Any]) -> ColumnElement[bool]:
    """MongoDB's {f: {$nin: [...]}}: a missing field is "not in" unless None is listed."""
    values = list(values)
    real = [v for v in values if v is not None]
    if None in values:
        return and_(column.is_not(None), column.not_in(real)) if real else column.is_not(None)
    return or_(column.not_in(real), column.is_(None)) if real else true()


def eq(column: Any, value: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], column.is_(None) if value is None else column == value)


def has_event(*conditions: ColumnElement[bool]) -> ColumnElement[bool]:
    """A vacancy with at least one history event matching all of `conditions`."""
    return exists().where(E.job_id == J.id, *conditions)


def sync_is(*conditions: ColumnElement[bool]) -> ColumnElement[bool]:
    """A vacancy whose Telegram outbox entry matches all of `conditions`."""
    return exists().where(JobSync.job_id == J.id, *conditions)


async def due_syncs(now: Any, limit: int) -> list[str]:
    """The vacancies whose status change Telegram has to show by `now`, the longest waiting first."""
    query = (
        select(JobSync.job_id)
        .where(JobSync.state == "pending", JobSync.next_at <= now)
        .order_by(JobSync.next_at)
        .limit(limit)
    )
    async with sql.session() as s:
        return list((await s.scalars(query)).all())


def group_condition(root: str) -> ColumnElement[bool]:
    """Every copy of a group: its root and whatever points at it."""
    return or_(J.id == root, J.group_id == root)


# --- documents -----------------------------------------------------------------------------------


def event_doc(event: JobEvent) -> dict[str, Any]:
    reverse: dict[str, str] = {v: k for k, v in EVENT_KEYS.items()}
    return {reverse.get(name, name): getattr(event, name) for name in EVENT_COLUMNS}


def event_row(job_id: str, position: int, event: dict[str, Any]) -> dict[str, Any]:
    # Every column, None where the event has no such key: rows inserted together need one shape.
    row: dict[str, Any] = {"job_id": job_id, "position": position, **dict.fromkeys(EVENT_COLUMNS)}
    for key, value in event.items():
        name = EVENT_KEYS.get(key, key)
        if name not in EVENT_COLUMNS:
            raise UnknownField(f"history event key {key!r}")
        row[name] = value
    return row


def to_doc(row: JobRow, events: Sequence[JobEvent] = (), sync: JobSync | None = None) -> dict[str, Any]:
    """The vacancy as a document: every field (None where it has none), `history`, `tg_sync`."""
    doc: dict[str, Any] = {"_id": row.id}
    for name in COLUMNS:
        doc[name] = getattr(row, name)
    note = row.seen_before or {}
    for key, inner in SIMILAR.items():
        doc[key] = note.get(inner)
    doc["history"] = [event_doc(e) for e in sorted(events, key=lambda e: e.position)] or None
    doc["tg_sync"] = {name: getattr(sync, name) for name in SYNC_COLUMNS} if sync else None
    return doc


def _split(fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    """Document fields → (column values, the "seen before" keys given, tg_sync keys given)."""
    values: dict[str, Any] = {}
    similar: dict[str, Any] | None = None
    sync: dict[str, Any] = {}
    for key, value in fields.items():
        if key in COLUMNS:
            values[key] = value
        elif key in SIMILAR:
            similar = similar or {}
            similar[SIMILAR[key]] = value
        elif key == "tg_sync":
            if value is None:
                sync = {"__delete__": True}
            else:
                sync.update(value)
        elif key.startswith("tg_sync."):
            sync[key.removeprefix("tg_sync.")] = value
        else:
            raise UnknownField(f"vacancy field {key!r}")
    unknown = set(sync) - set(SYNC_COLUMNS) - {"__delete__"}
    if unknown:
        raise UnknownField(f"tg_sync keys {sorted(unknown)}")
    return values, similar, sync


def from_job(job: Any) -> dict[str, Any]:
    """A Job (container.py) as document fields."""
    return {f.name: getattr(job, f.name) for f in dataclass_fields(job)}


# --- reading -------------------------------------------------------------------------------------


async def _attach(s: AsyncSession, rows: Sequence[JobRow], history: bool) -> list[dict[str, Any]]:
    ids = [r.id for r in rows]
    events: dict[str, list[JobEvent]] = {}
    syncs: dict[str, JobSync] = {}
    if ids:
        if history:
            for e in await s.scalars(select(E).where(E.job_id.in_(ids))):
                events.setdefault(e.job_id, []).append(e)
        for sync in await s.scalars(select(JobSync).where(JobSync.job_id.in_(ids))):
            syncs[sync.job_id] = sync
    return [to_doc(r, events.get(r.id, ()), syncs.get(r.id)) for r in rows]


async def find(
    where: ColumnElement[bool] | None = None,
    *,
    order: Sequence[Any] = (),
    limit: int | None = None,
    history: bool = True,
    description: bool = True,
) -> list[dict[str, Any]]:
    """The vacancies matching `where` as documents. `description=False` leaves it out (None)."""
    query = select(J)
    if where is not None:
        query = query.where(where)
    if order:
        query = query.order_by(*order)
    if limit is not None:
        query = query.limit(limit)
    async with sql.session() as s:
        rows = (await s.scalars(query)).all()
        docs = await _attach(s, rows, history)
    if not description:
        for doc in docs:
            doc["description"] = None
    return docs


async def get(job_id: str) -> dict[str, Any] | None:
    if not valid_id(job_id):
        return None
    found = await find(J.id == job_id)
    return found[0] if found else None


async def ids(where: ColumnElement[bool], *, order: Sequence[Any] = (), limit: int | None = None) -> list[str]:
    query = select(J.id).where(where)
    if order:
        query = query.order_by(*order)
    if limit is not None:
        query = query.limit(limit)
    async with sql.session() as s:
        return list((await s.scalars(query)).all())


async def distinct(column: Any, where: ColumnElement[bool]) -> list[Any]:
    async with sql.session() as s:
        return list((await s.scalars(select(column).where(where).distinct())).all())


async def count(where: ColumnElement[bool]) -> int:
    async with sql.session() as s:
        return int((await s.execute(select(func.count()).select_from(J).where(where))).scalar() or 0)


# --- writing -------------------------------------------------------------------------------------


def statements(docs: Iterable[dict[str, Any]]) -> tuple[list[str], list[Any]]:
    """The ids and the INSERT / UPDATE statements that store whole documents (`put`; the tests' helper
    runs the same ones on a plain connection). `_id` given or made; `group_id` is set after every row is
    in, so parents need not come first."""
    rows, events, syncs, groups = [], [], [], {}
    for doc in docs:
        doc = dict(doc)
        job_id = str(doc.pop("_id", None) or sql.new_id())
        history = doc.pop("history", None) or []
        values, similar, sync = _split(doc)
        groups[job_id] = values.pop("group_id", None)
        rows.append({**dict.fromkeys(COLUMNS), **values, "id": job_id, "group_id": None,
                     "seen_before": similar})  # fmt: skip
        events += [event_row(job_id, i, e) for i, e in enumerate(history)]
        if sync and "__delete__" not in sync:
            syncs.append({"job_id": job_id, **{name: sync.get(name) for name in SYNC_COLUMNS}})
    if not rows:
        return [], []
    steps: list[Any] = [insert(J).values(rows)]
    steps += [sql_update(J).where(J.id == i).values(group_id=g) for i, g in groups.items() if g is not None]
    if events:
        steps.append(insert(E).values(events))
    if syncs:
        steps.append(insert(JobSync).values(syncs))
    return [r["id"] for r in rows], steps


async def put(docs: Iterable[dict[str, Any]]) -> list[str]:
    """Store whole documents (a new run's vacancies). Returns their ids, in order."""
    ids, steps = statements(docs)
    if not steps:
        return []
    async with sql.session() as s:
        for step in steps:
            await s.execute(step)
        await s.commit()
    return ids


async def _apply(
    s: AsyncSession,
    job_id: str,
    fields: dict[str, Any],
    where: ColumnElement[bool] | None,
    event: dict[str, Any] | None,
) -> bool:
    values, similar, sync = _split(fields)
    condition = J.id == job_id if where is None else and_(J.id == job_id, where)
    if similar is not None:
        current = (await s.execute(select(J.seen_before).where(J.id == job_id))).scalar()
        values["seen_before"] = {**(current or {}), **similar}
    # Always an UPDATE, even with nothing to set: it checks the condition and locks the row, so the
    # event's position cannot be taken twice by writers racing on one vacancy.
    result = await s.execute(sql_update(J).where(condition).values(values or {"id": J.id}))
    if not result.rowcount:  # type: ignore[attr-defined]
        return False
    if sync.pop("__delete__", False):
        await s.execute(delete(JobSync).where(JobSync.job_id == job_id))
    if sync:
        present = await s.get(JobSync, job_id)
        if present is None:
            s.add(JobSync(job_id=job_id, **{"notify": False, "attempts": 0, "state": "pending", **sync}))
        else:
            for name, value in sync.items():
                setattr(present, name, value)
    if event is not None:
        last = (await s.execute(select(func.max(E.position)).where(E.job_id == job_id))).scalar()
        await s.execute(insert(E), [event_row(job_id, 0 if last is None else last + 1, event)])
    return True


async def update(
    job_id: str,
    fields: dict[str, Any],
    *,
    where: ColumnElement[bool] | None = None,
    event: dict[str, Any] | None = None,
) -> bool:
    """Set `fields` (and append `event` to the history) if the vacancy exists and matches `where`.

    One transaction. False — no such vacancy, or `where` no longer holds (a concurrent change).
    """
    async with sql.session() as s:
        changed = await _apply(s, job_id, fields, where, event)
        await s.commit()
    return changed


async def update_many(
    job_ids: Iterable[str],
    fields: dict[str, Any],
    *,
    where: ColumnElement[bool] | None = None,
    event: dict[str, Any] | None = None,
) -> int:
    """`update` for several vacancies in one transaction; how many changed."""
    changed = 0
    async with sql.session() as s:
        for job_id in job_ids:
            changed += await _apply(s, job_id, fields, where, event)
        await s.commit()
    return changed


async def update_where(where: ColumnElement[bool], fields: dict[str, Any]) -> int:
    """Set plain columns on every vacancy matching `where` (no history, no outbox)."""
    values, similar, sync = _split(fields)
    if similar is not None or sync:
        raise UnknownField("update_where takes plain columns only")
    async with sql.session() as s:
        result = await s.execute(sql_update(J).where(where).values(values))
        await s.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def increment(job_id: str, column: str) -> dict[str, Any] | None:
    """column += 1 (NULL counts as 0); the document as it was before, None if there is none."""
    if not valid_id(job_id):
        return None
    async with sql.session() as s:
        row = await s.get(J, job_id, with_for_update=True)
        if row is None:
            return None
        before = to_doc(row)
        setattr(row, column, (getattr(row, column) or 0) + 1)
        await s.commit()
    return before


async def rewrite_history(
    job_id: str, expected: list[dict[str, Any]], history: list[dict[str, Any]], fields: dict[str, Any] | None = None
) -> bool:
    """Replace the whole history (and set `fields`) if it is still `expected` — the backfill's CAS."""
    async with sql.session() as s:
        current = (await s.scalars(select(E).where(E.job_id == job_id).order_by(E.position))).all()
        if [event_doc(e) for e in current] != [event_doc_like(e) for e in expected]:
            return False
        if fields and not await _apply(s, job_id, fields, None, None):
            return False
        await s.execute(delete(E).where(E.job_id == job_id))
        if history:
            await s.execute(insert(E), [event_row(job_id, i, e) for i, e in enumerate(history)])
        await s.commit()
    return True


def event_doc_like(event: dict[str, Any]) -> dict[str, Any]:
    """A history event dict with every key a stored one has, for comparing with `event_doc`."""
    reverse = {v: k for k, v in EVENT_KEYS.items()}
    full: dict[str, Any] = {reverse.get(name, name): None for name in EVENT_COLUMNS}
    full.update(event)
    return full
