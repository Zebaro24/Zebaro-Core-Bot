"""Alembic environment: async engine, every model imported so autogenerate sees it."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import src.services.spotify.models  # noqa: F401 — registers the tables on Base.metadata
from src.db.sql import Base

config = context.config
# The bot configures logging itself; only a bare `alembic` run reads alembic.ini's.
if config.config_file_name is not None and not config.attributes.get("embedded"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url"):
    from src.config import settings

    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def _configure(connection: Connection | None = None) -> None:
    # SQLite cannot ALTER most things: batch mode rebuilds the table instead.
    context.configure(
        connection=connection,
        url=None if connection else config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        render_as_batch=True,
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure()
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
