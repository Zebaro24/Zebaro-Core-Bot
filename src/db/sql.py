"""SQL storage through SQLAlchemy: PostgreSQL in production, SQLite in the tests.

The engine is built on first use, not at import: tests swap ``src.config`` for a mock, and a
URL read from a MagicMock at import time would break every module that imports this one.
The schema is Alembic's (``migrations/``): the bot upgrades it to head at every start.

Only what both engines do the same goes into queries — the tests run on SQLite. Regexes go through
``column.regexp_match``: ``~`` on PostgreSQL, Python's ``re`` on SQLite.
"""

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, DateTime, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from src.config import settings

logger = logging.getLogger("db.sql")

ROOT = Path(__file__).resolve().parent.parent.parent

_DATE = "$date"


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {_DATE: value.isoformat()}
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if len(value) == 1 and _DATE in value:
            return datetime.fromisoformat(value[_DATE])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


class Json(TypeDecorator):
    """JSON (JSONB on PostgreSQL) whose datetimes come back as datetimes: a vacancy's nested dates
    (company_history[].at, seen_before.seen_at) are compared and formatted like the top-level ones.

    Python's None is SQL NULL, never a JSON `null`: `IS NULL` and NOT NULL mean what they say."""

    impl = JSON(none_as_null=True)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB(none_as_null=True))
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return None if value is None else _encode(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        return None if value is None else _decode(value)


class UtcDateTime(TypeDecorator):
    """A naive UTC datetime, whatever comes in — what MongoDB did: an aware value is converted to UTC
    and stored without its zone, and comes back naive. asyncpg refuses an aware value for a column
    without a time zone outright, and SQLite would store it as given: one rule for both."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value


# The database is down or unreachable: SQLAlchemy's errors, and the OSError asyncpg raises when it
# cannot reach the server at all (a stopped container's name does not resolve: socket.gaierror).
UNAVAILABLE: tuple[type[Exception], ...] = (SQLAlchemyError, OSError)

_counter = int.from_bytes(os.urandom(3), "big")
_process = os.urandom(5)


def new_id() -> str:
    """A 24-hex id in MongoDB's ObjectId layout (time, random, counter): the stored vacancies keep
    the ids Telegram's buttons and /jobs/r links carry, and new ones look and sort the same."""
    global _counter
    _counter = (_counter + 1) % 0x1000000
    return (int(time.time()).to_bytes(4, "big") + _process + _counter.to_bytes(3, "big")).hex()


class Base(DeclarativeBase):
    pass


class Kv(Base):
    """Small singletons of the bot's own state: {"search_window": {...}, "home_proxy_alert": {...}}."""

    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(Json, nullable=False)


_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessions
    if _engine is None:
        _engine = create_async_engine(settings.database_url)
        if _engine.dialect.name == "sqlite":
            # SQLite ignores foreign keys unless asked, per connection.
            @event.listens_for(_engine.sync_engine, "connect")
            def _foreign_keys(dbapi_connection, _record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session() -> AsyncSession:
    """``async with session() as s:`` — one unit of work."""
    get_engine()
    assert _sessions is not None
    return _sessions()


async def kv_get(key: str) -> dict[str, Any] | None:
    async with session() as s:
        row = await s.get(Kv, key)
        return dict(row.value) if row is not None else None


async def kv_merge(key: str, fields: dict[str, Any]) -> None:
    """Set `fields` in the value of `key`, the other fields kept; the row made if missing."""
    async with session() as s:
        row = await s.get(Kv, key, with_for_update=True)
        if row is None:
            s.add(Kv(key=key, value=dict(fields)))
        else:
            row.value = {**row.value, **fields}
        await s.commit()


async def kv_claim(key: str, field: str, value: Any) -> bool:
    """Set value[field] = value unless it is that already: True only for the one writer that set it.

    Two racing writers: the row lock (or, for a missing row, the primary key) lets one through."""
    try:
        async with session() as s:
            row = await s.get(Kv, key, with_for_update=True)
            if row is not None and row.value.get(field) == value:
                return False
            if row is None:
                s.add(Kv(key=key, value={field: value}))
            else:
                row.value = {**row.value, field: value}
            await s.commit()
    except IntegrityError:  # the other writer made the row first
        return False
    return True


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    config.attributes["embedded"] = True
    return config


async def migrate() -> None:
    """Bring the schema to head. Alembic runs its own event loop, hence the thread."""
    await asyncio.to_thread(command.upgrade, alembic_config(), "head")
    logger.info("SQL schema is up to date (%s)", get_engine().url.render_as_string(hide_password=True))
