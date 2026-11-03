"""The owner's journal: what he changed in his approach (CV, cover letter, strategy) and when.

The funnel shows it next to the numbers of the same period: "the replies went up after the new
CV" is then visible on one timeline. It is correlation, not an experiment — with tens of
applications a month and a few changes in a row the cause cannot be separated.

Stored in SQL (the project's rule for new storage), time as Unix int.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.db import sql
from src.db.sql import Base

KINDS = ("cv", "letter", "strategy", "market", "other")
ACTORS = ("user", "ai")
MAX_TEXT = 2000


class JournalEntry(Base):
    __tablename__ = "job_journal"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[int] = mapped_column(BigInteger, index=True)  # when the change was made
    recorded_at: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(16))


def to_unix(moment: datetime) -> int:
    """A naive UTC datetime (the bot's convention) → Unix seconds."""
    return int(moment.replace(tzinfo=UTC).timestamp())


def from_unix(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC).replace(tzinfo=None)


def _open() -> AsyncSession:
    return sql.session()


def public_entry(entry: JournalEntry) -> dict[str, Any]:
    from src.services.job_searcher.jobs_api import utc

    return {
        "id": str(entry.id),
        "occurred_at": utc(from_unix(entry.occurred_at)),
        "recorded_at": utc(from_unix(entry.recorded_at)),
        "kind": entry.kind,
        "text": entry.text,
        "actor": entry.actor,
    }


async def add_entry(kind: str, text: str, actor: str, occurred_at: datetime | None = None) -> dict[str, Any]:
    now = datetime.utcnow()
    entry = JournalEntry(
        occurred_at=to_unix(occurred_at or now), recorded_at=to_unix(now), kind=kind, text=text, actor=actor
    )
    async with _open() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    return public_entry(entry)


async def entries(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """The entries made in [start, end), oldest first."""
    query = (
        select(JournalEntry)
        .where(JournalEntry.occurred_at >= to_unix(start), JournalEntry.occurred_at < to_unix(end))
        .order_by(JournalEntry.occurred_at, JournalEntry.id)
    )
    async with _open() as session:
        return [public_entry(entry) for entry in (await session.scalars(query)).all()]
