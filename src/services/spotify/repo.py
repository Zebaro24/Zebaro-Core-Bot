"""Queries of the Spotify service: one place that knows the tables."""

import json
import secrets
import time
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.spotify.models import Adjustment, Alias, Charge, JarTransaction, Member, Notice, State

# State keys
JAR = "jar_id"
JAR_SEND = "jar_send_id"
CARD = "card_id"
CURSOR = "cursor"  # the poll has everything up to this Unix time
WEBHOOK = "webhook_url"
HISTORY = "history"  # {"since": ..., "done": ...} of the full reload


async def get_state(s: AsyncSession, key: str, default: Any = None) -> Any:
    row = await s.get(State, key)
    return json.loads(row.value) if row else default


async def set_state(s: AsyncSession, key: str, value: Any) -> None:
    row = await s.get(State, key)
    if row:
        row.value = json.dumps(value)
    else:
        s.add(State(key=key, value=json.dumps(value)))


# ── Members ──────────────────────────────────────────────────────────────────


async def members(s: AsyncSession) -> list[Member]:
    return list((await s.scalars(select(Member).order_by(Member.is_owner.desc(), Member.id))).all())


async def owner(s: AsyncSession) -> Member | None:
    return await s.scalar(select(Member).where(Member.is_owner))


async def member_by_tg(s: AsyncSession, tg_id: int) -> Member | None:
    return await s.scalar(select(Member).where(Member.tg_id == tg_id))


async def member_by_invite(s: AsyncSession, code: str) -> Member | None:
    return await s.scalar(select(Member).where(Member.invite_code == code))


def new_invite_code() -> str:
    return secrets.token_urlsafe(9)


async def add_member(
    s: AsyncSession, name: str, joined_on: date, alias: str | None = None, is_owner: bool = False
) -> Member:
    member = Member(name=name, joined_on=joined_on, invite_code=new_invite_code(), is_owner=is_owner, aliases=[])
    s.add(member)
    await s.flush()
    if alias:
        await assign_alias(s, alias, member.id)
    return member


async def assign_alias(s: AsyncSession, name: str, member_id: int | None) -> int:
    """Bind a sender name to a member (None — "not ours") and re-file their top-ups."""
    alias = await s.get(Alias, name)
    if alias:
        alias.member_id = member_id
    else:
        s.add(Alias(name=name, member_id=member_id))
    rows = (await s.scalars(select(JarTransaction).where(JarTransaction.sender == name))).all()
    for row in rows:
        row.member_id = member_id
    await s.flush()
    return len(rows)


async def aliases(s: AsyncSession) -> dict[str, int | None]:
    return {a.name: a.member_id for a in (await s.scalars(select(Alias))).all()}


async def first_topup(s: AsyncSession, sender: str) -> int | None:
    return await s.scalar(select(func.min(JarTransaction.time)).where(JarTransaction.sender == sender))


async def unknown_senders(s: AsyncSession) -> list[tuple[str, int, int]]:
    """(sender, top-ups, total kopecks) of names nobody has been told about yet."""
    known = select(Alias.name)
    query = (
        select(JarTransaction.sender, func.count(), func.sum(JarTransaction.amount))
        .where(JarTransaction.kind == "topup", JarTransaction.sender.is_not(None), JarTransaction.sender.not_in(known))
        .group_by(JarTransaction.sender)
        .order_by(func.sum(JarTransaction.amount).desc())
    )
    return [(str(name), int(count), int(total)) for name, count, total in (await s.execute(query)).all()]


# ── History ──────────────────────────────────────────────────────────────────


async def charges(s: AsyncSession) -> list[Charge]:
    return list((await s.scalars(select(Charge).order_by(Charge.time))).all())


async def transactions(s: AsyncSession, member_id: int | None = None) -> list[JarTransaction]:
    query = select(JarTransaction).order_by(JarTransaction.time)
    if member_id is not None:
        query = query.where(JarTransaction.member_id == member_id)
    return list((await s.scalars(query)).all())


async def adjustments(s: AsyncSession, member_id: int | None = None) -> list[Adjustment]:
    query = select(Adjustment).order_by(Adjustment.time)
    if member_id is not None:
        query = query.where(Adjustment.member_id == member_id)
    return list((await s.scalars(query)).all())


async def add_adjustment(s: AsyncSession, member_id: int, amount: int, note: str) -> Adjustment:
    adjustment = Adjustment(member_id=member_id, amount=amount, note=note, time=int(time.time()))
    s.add(adjustment)
    await s.flush()
    return adjustment


async def last_charge(s: AsyncSession) -> Charge | None:
    return await s.scalar(select(Charge).where(Charge.amount > 0).order_by(Charge.time.desc()).limit(1))


# ── Notices ──────────────────────────────────────────────────────────────────


async def claim_notice(s: AsyncSession, member_id: int, kind: str, period: str) -> bool:
    """True the first time for (member, kind, period): the caller sends, a repeat does not."""
    if await s.get(Notice, (member_id, kind, period)):
        return False
    s.add(Notice(member_id=member_id, kind=kind, period=period))
    await s.flush()
    return True


async def forget_notices(s: AsyncSession, kind: str, period: str) -> None:
    await s.execute(delete(Notice).where(Notice.kind == kind, Notice.period == period))
