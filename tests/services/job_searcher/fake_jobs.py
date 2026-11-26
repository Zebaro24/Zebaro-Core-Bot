"""The stored vacancies for the job searcher's tests: a list of documents backed by the real tables.

`jobs.docs` is a plain list of vacancy documents (the shape store.py reads and writes). Whatever the
test puts in or changes there is written to the SQLite database before the code under test opens a
session, and what the code wrote is read back the next time the test looks at `jobs.docs`. So the
tests keep stating vacancies as documents while every query and every write runs as real SQL.

Use with the `sql_db` fixture (tests/conftest.py): `jobs = SqlJobs(sql_db, mocker)`.
"""

import copy
from typing import Any

from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from src.services.job_searcher import store
from src.services.job_searcher.models import JobEvent, JobRow, JobSync


class SqlJobs:
    def __init__(self, sql_db: Any, mocker: Any) -> None:
        url = sql_db.get_engine().url
        if url.get_backend_name() != "sqlite":
            raise RuntimeError("SqlJobs mirrors a SQLite test database only")
        self._sync = create_engine(f"sqlite:///{url.database}", poolclass=NullPool)  # no connection left open
        self._docs: list[dict[str, Any]] = []
        self._pushed: list[dict[str, Any]] = []
        self._written = False
        opened = sql_db.session

        def session() -> Any:
            self._push()
            s = opened()
            event.listen(s.sync_session, "after_commit", self._mark)
            return s

        mocker.patch.object(sql_db, "session", session)

    def _mark(self, _session: Any) -> None:
        self._written = True

    @property
    def docs(self) -> list[dict[str, Any]]:
        if self._written:
            self._pull()
        return self._docs

    @docs.setter
    def docs(self, value: list[dict[str, Any]]) -> None:
        self._docs = list(value)

    def by_id(self, job_id: Any) -> dict[str, Any]:
        return next(doc for doc in self.docs if doc["_id"] == str(job_id))

    def _push(self) -> None:
        if self._docs == self._pushed and not self._written:
            return
        if self._written:  # the code wrote since the test last looked: nothing local to send
            self._pull()
            return
        _ids, steps = store.statements(self._docs)
        with self._sync.begin() as c:
            for table in (JobSync, JobEvent, JobRow):
                c.execute(delete(table))
            for step in steps:
                c.execute(step)
        self._pushed = copy.deepcopy(self._docs)
        self._pull()

    def _pull(self) -> None:
        with Session(self._sync) as s:
            rows = s.scalars(select(JobRow).order_by(text("jobs.rowid"))).all()
            events: dict[str, list[JobEvent]] = {}
            for e in s.scalars(select(JobEvent)):
                events.setdefault(e.job_id, []).append(e)
            syncs = {x.job_id: x for x in s.scalars(select(JobSync))}
            docs = [store.to_doc(r, events.get(r.id, ()), syncs.get(r.id)) for r in rows]
        self._docs, self._pushed, self._written = docs, copy.deepcopy(docs), False


class _MetaDoc(dict):
    """One old `meta` document; setting a key writes it through."""

    def __init__(self, owner: "SqlMeta", key: str, value: dict[str, Any]) -> None:
        super().__init__(value)
        self._owner, self._key = owner, key

    def __setitem__(self, name: str, value: Any) -> None:
        super().__setitem__(name, value)
        self._owner.write(self._key, {k: v for k, v in self.items() if k != "_id"})


class SqlMeta:
    """The bot's small state as the old `meta` collection: {_id: "ai_notes:500", chat_id, entries}, …

    Backed by kv, review_summaries and ai_note_messages; by_id() reads, item assignment writes."""

    def __init__(self, sql_db: Any) -> None:
        self._sync = create_engine(f"sqlite:///{sql_db.get_engine().url.database}", poolclass=NullPool)

    @staticmethod
    def _place(key: str) -> tuple[Any, Any]:
        from src.db.sql import Kv
        from src.services.job_searcher.models import AiNoteMessage, ReviewSummary

        kind, _, rest = key.partition(":")
        if kind == "review_summary":
            return ReviewSummary, rest
        if kind == "ai_notes" and rest.isdigit():
            return AiNoteMessage, int(rest)
        return Kv, key

    def write(self, key: str, value: dict[str, Any]) -> None:
        from src.db.sql import Kv
        from src.services.job_searcher.models import AiNoteMessage, ReviewSummary

        model, pk = self._place(key)
        with Session(self._sync) as s:
            row = s.get(model, pk)
            if model is Kv:
                row = row or s.merge(Kv(key=pk, value={}))
                row.value = dict(value)
            elif model is ReviewSummary:
                row = row or s.merge(ReviewSummary(day=pk, parts=[]))
                row.parts = value.get("parts") or []
            else:
                row = row or s.merge(AiNoteMessage(message_id=pk, chat_id=0, entries=[]))
                row.chat_id, row.entries = value.get("chat_id") or 0, value.get("entries") or []
            s.commit()

    @property
    def docs(self) -> list[dict[str, Any]]:
        from src.db.sql import Kv
        from src.services.job_searcher.models import AiNoteMessage, ReviewSummary

        with Session(self._sync) as s:
            docs = [{"_id": r.key, **r.value} for r in s.scalars(select(Kv))]
            docs += [{"_id": f"review_summary:{r.day}", "parts": r.parts} for r in s.scalars(select(ReviewSummary))]
            docs += [
                {"_id": f"ai_notes:{r.message_id}", "chat_id": r.chat_id, "entries": r.entries}
                for r in s.scalars(select(AiNoteMessage))
            ]
        return docs

    def by_id(self, key: str) -> dict[str, Any]:
        doc = next(doc for doc in self.docs if doc["_id"] == key)
        return _MetaDoc(self, key, doc)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        """Only {"_id": key} with $set — how the tests seed a marker."""
        key = query["_id"]
        current = next((doc for doc in self.docs if doc["_id"] == key), None)
        if current is None and not upsert:
            return
        value = {k: v for k, v in (current or {}).items() if k != "_id"}
        self.write(key, {**value, **update["$set"]})
