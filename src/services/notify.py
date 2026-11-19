"""Claude's notifications: the request model and the record of messages still in the chat.

Every `take_*` takes records out (select + delete) and returns their message ids, so the caller
deletes each Telegram message once. Stored in SQL (the project's rule for new storage), time as Unix
int. The database failing → nothing is remembered and nothing is taken: the notification still goes
out, it just stays until the owner taps ✓.
"""

import logging
import time
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, String, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.db import sql
from src.db.sql import Base

logger = logging.getLogger("services.notify")

TTL = timedelta(hours=12)
SWEEP_MINUTES = 30
SWEEP_JOB_ID = "notify_sweep"


class Notice(BaseModel):
    """The body of POST /notify. Unknown fields are ignored: the contract only ever adds."""

    model_config = ConfigDict(extra="ignore")

    project: str = Field(min_length=1, max_length=80)
    repo: str | None = Field(default=None, max_length=80)
    event: Literal["done", "question", "plan", "attention"]
    title: str = Field(min_length=1, max_length=80)
    text: str = Field(default="", max_length=1000)
    session: str = Field(min_length=1, max_length=128)


class NotifyMessage(Base):
    """A notification still in the owner's chat."""

    __tablename__ = "notify_messages"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    project: Mapped[str] = mapped_column(String(80), index=True)
    repo: Mapped[str | None] = mapped_column(String(80))
    session: Mapped[str] = mapped_column(String(128), index=True)
    sent_at: Mapped[int] = mapped_column(BigInteger, index=True)


def _open() -> AsyncSession:
    return sql.session()


async def _take(condition: Any) -> list[int]:
    try:
        async with _open() as s:
            ids = list((await s.scalars(select(NotifyMessage.message_id).where(condition))).all())
            if ids:
                await s.execute(delete(NotifyMessage).where(NotifyMessage.message_id.in_(ids)))
                await s.commit()
    except SQLAlchemyError as e:
        logger.warning("Notify records unavailable: %s", e)
        return []
    return ids


async def take_project(project: str) -> list[int]:
    return await _take(NotifyMessage.project == project)


async def take_session(session: str) -> list[int]:
    return await _take(NotifyMessage.session == session)


async def take_message(message_id: int) -> list[int]:
    return await _take(NotifyMessage.message_id == message_id)


async def take_expired(now: float | None = None) -> list[int]:
    cutoff = int((now if now is not None else time.time()) - TTL.total_seconds())
    return await _take(NotifyMessage.sent_at < cutoff)


async def remember(notice: Notice, message_id: int, now: float | None = None) -> None:
    record = NotifyMessage(
        message_id=message_id,
        project=notice.project,
        repo=notice.repo,
        session=notice.session,
        sent_at=int(now if now is not None else time.time()),
    )
    try:
        async with _open() as s:
            s.add(record)
            await s.commit()
    except SQLAlchemyError as e:
        logger.warning("Notify message %s not remembered: %s", message_id, e)
