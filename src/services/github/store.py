"""What the owner chose for GitHub, in SQL: forum topics, each repo's level and topic, the live messages.

A repo nobody configured yet is "all" without a topic: its critical events still reach the owner's chat,
nothing goes to the forum until a topic is chosen. Several repos may share one topic (one system, one chat).
Live messages: one forum message per commit or release, edited as its workflows run; one owner's-chat
message per failing workflow, edited when it is green again. Their state is a small JSON document.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint, delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.db import sql
from src.db.sql import Base

logger = logging.getLogger("services.github.store")

Level = Literal["all", "fails", "off"]
LEVELS: tuple[Level, ...] = ("all", "fails", "off")
DEFAULT_LEVEL: Level = "all"
# Live-message records older than this are dropped (the messages stay in the chat).
MESSAGE_TTL = 14 * 24 * 3600


class GithubTopic(Base):
    __tablename__ = "github_topics"
    __table_args__ = (UniqueConstraint("chat_id", "thread_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    thread_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(128))


class GithubRepo(Base):
    __tablename__ = "github_repos"

    # A short id for callback data (64 bytes): a repo's full name may not fit.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(140), unique=True)
    level: Mapped[str] = mapped_column(String(8), default=DEFAULT_LEVEL)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("github_topics.id", ondelete="SET NULL"))


class GithubMessage(Base):
    __tablename__ = "github_messages"

    key: Mapped[str] = mapped_column(String(220), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    state: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[int] = mapped_column(BigInteger, index=True)


@dataclass(frozen=True)
class Topic:
    id: int
    chat_id: int
    thread_id: int
    name: str


@dataclass(frozen=True)
class RepoConfig:
    id: int
    full_name: str
    level: Level
    topic: Topic | None


@dataclass
class Live:
    key: str
    chat_id: int
    message_id: int
    state: dict[str, Any]


def _open() -> AsyncSession:
    return sql.session()


def _topic(row: GithubTopic | None) -> Topic | None:
    return Topic(row.id, row.chat_id, row.thread_id, row.name) if row else None


def _level(value: str) -> Level:
    return value if value in LEVELS else DEFAULT_LEVEL


# ── repos ──────────────────────────────────────────────────────────────────────


async def repo(full_name: str) -> RepoConfig:
    """The repo's settings; an unknown repo is added with the default (it is in the App, so it is the owner's)."""
    async with _open() as s:
        row = await s.scalar(select(GithubRepo).where(GithubRepo.full_name == full_name))
        if row is None:
            s.add(GithubRepo(full_name=full_name, level=DEFAULT_LEVEL))
            try:
                await s.commit()
            except IntegrityError:  # the repo's other first event got there first
                await s.rollback()
            row = await s.scalar(select(GithubRepo).where(GithubRepo.full_name == full_name))
            assert row is not None
        topic = await s.get(GithubTopic, row.topic_id) if row.topic_id else None
        return RepoConfig(row.id, row.full_name, _level(row.level), _topic(topic))


async def repo_by_id(repo_id: int) -> RepoConfig | None:
    async with _open() as s:
        row = await s.get(GithubRepo, repo_id)
        if row is None:
            return None
        topic = await s.get(GithubTopic, row.topic_id) if row.topic_id else None
        return RepoConfig(row.id, row.full_name, _level(row.level), _topic(topic))


async def sync_repos(names: list[str]) -> list[RepoConfig]:
    """Every repo the App sees, in that order; new ones get the default, settings of the rest stay."""
    async with _open() as s:
        rows = {r.full_name: r for r in (await s.scalars(select(GithubRepo))).all()}
        for name in names:
            if name not in rows:
                rows[name] = GithubRepo(full_name=name, level=DEFAULT_LEVEL)
                s.add(rows[name])
        await s.commit()
        topics = {t.id: t for t in (await s.scalars(select(GithubTopic))).all()}
        return [
            RepoConfig(r.id, r.full_name, _level(r.level), _topic(topics.get(r.topic_id) if r.topic_id else None))
            for r in (rows[n] for n in names)
        ]


async def set_level(repo_id: int, level: Level) -> None:
    async with _open() as s:
        row = await s.get(GithubRepo, repo_id)
        if row is not None:
            row.level = level
            await s.commit()


async def set_topic(repo_id: int, topic_id: int | None) -> None:
    async with _open() as s:
        row = await s.get(GithubRepo, repo_id)
        if row is not None:
            row.topic_id = topic_id
            await s.commit()


async def repos_in_topic(topic_id: int) -> list[str]:
    async with _open() as s:
        return list((await s.scalars(select(GithubRepo.full_name).where(GithubRepo.topic_id == topic_id))).all())


# ── topics ─────────────────────────────────────────────────────────────────────


TOPICS_SHOWN = 20


async def topics() -> list[Topic]:
    """The topics offered in /github, by name — at most TOPICS_SHOWN, so a busy forum cannot flood the screen."""
    async with _open() as s:
        rows = (await s.scalars(select(GithubTopic).order_by(GithubTopic.name).limit(TOPICS_SHOWN))).all()
        return [Topic(r.id, r.chat_id, r.thread_id, r.name) for r in rows]


async def forum_chats() -> set[int]:
    async with _open() as s:
        return set((await s.scalars(select(GithubTopic.chat_id))).all())


async def save_topic(chat_id: int, thread_id: int, name: str | None = None) -> Topic:
    """Add a topic, or rename a known one when a name is given."""
    async with _open() as s:
        row = await s.scalar(
            select(GithubTopic).where(GithubTopic.chat_id == chat_id, GithubTopic.thread_id == thread_id)
        )
        if row is None:
            row = GithubTopic(chat_id=chat_id, thread_id=thread_id, name=name or f"Тема {thread_id}")
            s.add(row)
        elif name:
            row.name = name
        await s.commit()
        return Topic(row.id, row.chat_id, row.thread_id, row.name)


async def topic(topic_id: int) -> Topic | None:
    async with _open() as s:
        return _topic(await s.get(GithubTopic, topic_id))


async def replace_topic(old_id: int, chat_id: int, thread_id: int, name: str) -> Topic:
    """A topic created again in place of a deleted one: its repos move over, the old record goes."""
    new = await save_topic(chat_id, thread_id, name)
    async with _open() as s:
        for row in (await s.scalars(select(GithubRepo).where(GithubRepo.topic_id == old_id))).all():
            row.topic_id = new.id
        await s.execute(delete(GithubTopic).where(GithubTopic.id == old_id))
        await s.commit()
    return new


# ── live messages ──────────────────────────────────────────────────────────────


async def live(key: str) -> Live | None:
    try:
        async with _open() as s:
            row = await s.get(GithubMessage, key)
            return Live(row.key, row.chat_id, row.message_id, json.loads(row.state)) if row else None
    except SQLAlchemyError as e:
        logger.warning("GitHub message %s unreadable: %s", key, e)
        return None


async def live_by_message(chat_id: int, message_id: int) -> Live | None:
    async with _open() as s:
        row = await s.scalar(
            select(GithubMessage).where(GithubMessage.chat_id == chat_id, GithubMessage.message_id == message_id)
        )
        return Live(row.key, row.chat_id, row.message_id, json.loads(row.state)) if row else None


async def keep(item: Live, now: float | None = None) -> None:
    try:
        async with _open() as s:
            row = await s.get(GithubMessage, item.key)
            if row is None:
                row = GithubMessage(key=item.key, sent_at=int(now if now is not None else time.time()))
                s.add(row)
            row.chat_id, row.message_id = item.chat_id, item.message_id
            row.state = json.dumps(item.state, ensure_ascii=False)
            await s.commit()
    except SQLAlchemyError as e:
        logger.warning("GitHub message %s not remembered: %s", item.key, e)


async def forget(key: str) -> None:
    try:
        async with _open() as s:
            await s.execute(delete(GithubMessage).where(GithubMessage.key == key))
            await s.commit()
    except SQLAlchemyError as e:
        logger.warning("GitHub message %s not forgotten: %s", key, e)


async def fixed_before(cutoff: float) -> list[Live]:
    """Owner's-chat messages turned "снова зелёный" before `cutoff`: due for deletion."""
    try:
        async with _open() as s:
            rows = (await s.scalars(select(GithubMessage).where(GithubMessage.key.like("fixed:%")))).all()
            items = [Live(r.key, r.chat_id, r.message_id, json.loads(r.state)) for r in rows]
    except SQLAlchemyError as e:
        logger.warning("Fixed GitHub messages unreadable: %s", e)
        return []
    return [i for i in items if float(i.state.get("fixed_at", 0)) < cutoff]


async def prune(now: float | None = None) -> None:
    cutoff = int((now if now is not None else time.time()) - MESSAGE_TTL)
    try:
        async with _open() as s:
            await s.execute(delete(GithubMessage).where(GithubMessage.sent_at < cutoff))
            await s.commit()
    except SQLAlchemyError as e:
        logger.warning("GitHub messages not pruned: %s", e)
