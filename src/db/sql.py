"""SQL storage through SQLAlchemy: SQLite now, Postgres later by changing DATABASE_URL.

The engine is built on first use, not at import: tests swap ``src.config`` for a mock, and a
URL read from a MagicMock at import time would break every module that imports this one.
The schema is Alembic's (``migrations/``): the bot upgrades it to head at every start.
"""

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

logger = logging.getLogger("db.sql")

ROOT = Path(__file__).resolve().parent.parent.parent


class Base(DeclarativeBase):
    pass


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
