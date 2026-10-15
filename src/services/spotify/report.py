"""One picture of the subscription for every screen and notice: ledger, next charge, money.

Anything that needs the network (rate, balances) degrades to None instead of failing: a
screen without the jar balance is still worth showing.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.config import settings
from src.db.sql import session
from src.services.spotify import ledger, monobank, repo, schedule
from src.services.spotify.models import Charge, Member

logger = logging.getLogger("services.spotify.report")


def tz() -> ZoneInfo:
    return ZoneInfo(settings.tz)


def today() -> date:
    return datetime.now(tz()).date()


@dataclass
class Money:
    """What the owner needs on the day: the card pays, the jar refills it."""

    card: int | None = None
    jar: int | None = None

    def advice(self, amount: int) -> tuple[str, int]:
        """("ok" | "withdraw" | "short" | "unknown", kopecks): what to do before the charge."""
        if self.card is None:
            return "unknown", 0
        if self.card >= amount:
            return "ok", 0
        missing = amount - self.card
        if self.jar is not None and self.jar >= missing:
            return "withdraw", missing
        return "short", missing - (self.jar or 0)


@dataclass
class Snapshot:
    members: list[Member]
    book: ledger.Ledger
    charges: list[Charge]
    upcoming: schedule.Forecast | None
    shares: dict[int, int] = field(default_factory=dict)  # next charge, per member
    money: Money = field(default_factory=Money)
    send_url: str = ""
    configured: bool = True

    @property
    def active(self) -> list[Member]:
        """Members still in the plan (a join date in the future counts: they are coming)."""
        day = today()
        return [m for m in self.members if m.left_on is None or m.left_on > day]

    @property
    def last_charge(self) -> Charge | None:
        paid = [c for c in self.charges if c.amount > 0]
        return paid[-1] if paid else None

    def share(self, member: Member) -> int:
        return self.shares.get(member.id, 0)

    def pay_url(self, amount: int) -> str:
        if not self.send_url:
            return ""
        # Whole hryvnias, rounded up: the jar page takes the amount as typed.
        return f"{self.send_url}?a={math.ceil(amount / 100)}" if amount > 0 else self.send_url


async def snapshot(money: bool = False) -> Snapshot:
    async with session() as s:
        members = await repo.members(s)
        charges = await repo.charges(s)
        book = ledger.build(members, charges, await repo.transactions(s), await repo.adjustments(s), tz())
        jar_id = await repo.get_state(s, repo.JAR)
        card_id = await repo.get_state(s, repo.CARD)
        send_id = await repo.get_state(s, repo.JAR_SEND, "")
    snap = Snapshot(
        members=members,
        book=book,
        charges=charges,
        upcoming=None,
        send_url=f"{monobank.SEND_URL}/{send_id}" if send_id else "",
        configured=bool(jar_id and card_id),
    )
    snap.upcoming = await _forecast(snap.last_charge)
    if snap.upcoming:
        day = snap.upcoming.day
        snap.shares = ledger.split(snap.upcoming.amount, [m for m in members if m.active_on(day)])
    if money and snap.configured:
        snap.money = await _money(jar_id, card_id)
    return snap


async def _forecast(last: Charge | None) -> schedule.Forecast | None:
    last_day = ledger.local_day(last.time, tz()) if last else None
    upcoming = schedule.next_charge(today(), last_day)
    if last is None:
        return None
    if last.currency_code == monobank.UAH:
        return schedule.Forecast(day=upcoming, amount=last.amount, price=last.amount, rate=1.0)
    try:
        rate = await monobank.rate(last.currency_code)
    except monobank.MonobankError as e:
        logger.info("No rate for the forecast, using the last charge: %s", e)
        return schedule.Forecast(
            day=upcoming, amount=last.amount, price=last.operation_amount, rate=last.amount / last.operation_amount
        )
    markup = schedule.markup(last.amount, last.operation_amount, last.rate)
    return schedule.forecast(upcoming, last.operation_amount, rate, markup)


async def _money(jar_id: str, card_id: str) -> Money:
    try:
        accounts = {a.id: a for a in monobank.parse_accounts(await monobank.client_info())}
    except monobank.MonobankError as e:
        logger.info("No balances: %s", e)
        return Money()
    card, jar = accounts.get(card_id), accounts.get(jar_id)
    return Money(card=card.balance if card else None, jar=jar.balance if jar else None)
