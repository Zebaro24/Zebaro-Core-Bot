"""Shared fixtures.

`sql_db` — a real SQLite database with every table of the models, in place of PostgreSQL: the code
under test opens sessions through `src.db.sql` as in production. The tests mock `src.config` at import
time, so `src.db.sql` is imported here only when the fixture runs, after the test module did that.

`TEST_DATABASE_URL=postgresql+asyncpg://…` runs the same tests on a real PostgreSQL (every table is
dropped and made again per test — a scratch database only): the check that SQLite and PostgreSQL
agree on what the code asks of them. CI does not set it.
"""

import os

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest_asyncio.fixture
async def sql_db(tmp_path, monkeypatch):
    import src.services.job_searcher.models
    import src.services.vpn.traffic  # noqa: F401
    from src.db import sql

    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    # No pool: the API tests drive the app on an event loop of their own, and a pooled connection
    # belongs to the loop that opened it.
    engine = create_async_engine(url, poolclass=NullPool)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(sql.Base.metadata.drop_all)
        await connection.run_sync(sql.Base.metadata.create_all)
    monkeypatch.setattr(sql, "_engine", engine)
    monkeypatch.setattr(sql, "_sessions", async_sessionmaker(engine, expire_on_commit=False))
    yield sql
    await engine.dispose()
