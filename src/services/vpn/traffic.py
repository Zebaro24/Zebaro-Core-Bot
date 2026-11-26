"""Traffic history and the notices that come from watching the VPN.

WireGuard's transfer counters live in the kernel and start from zero whenever the interface
restarts (a container restart, a reboot). A snapshot every few minutes turns them into running
totals that survive that, and into per-day traffic for "today" and "this week".

Stored in SQL (`vpn_clients`, `vpn_traffic_daily`); one writer — the snapshot job — so a read
followed by a write needs no locking.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import BigInteger, Integer, String, Text, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from src.db import sql
from src.db.sql import Base, UtcDateTime
from src.services.vpn.client import VpnClient

logger = logging.getLogger("vpn.traffic")


class ClientState(Base):
    """One wg-easy client as the bot watches it: running totals across counter restarts."""

    __tablename__ = "vpn_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # wg-easy's id
    name: Mapped[str | None] = mapped_column(Text)
    ipv4: Mapped[str | None] = mapped_column(String(15))
    last_rx: Mapped[int | None] = mapped_column(BigInteger)
    last_tx: Mapped[int | None] = mapped_column(BigInteger)
    total_rx: Mapped[int | None] = mapped_column(BigInteger)
    total_tx: Mapped[int | None] = mapped_column(BigInteger)
    seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    first_connected_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    expiry_noticed_for: Mapped[str | None] = mapped_column(String(40))


class TrafficDay(Base):
    """A client's traffic on one local day ("2026-11-26")."""

    __tablename__ = "vpn_traffic_daily"

    client_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    rx: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tx: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


EXPIRY_NOTICE = timedelta(days=1)
# A client older than this that the bot has never seen was connected before the bot started
# watching (the first deploy): no "connected for the first time" for it.
FIRST_CONNECT_WINDOW = timedelta(days=1)


@dataclass
class Totals:
    rx: int = 0
    tx: int = 0

    @property
    def total(self) -> int:
        return self.rx + self.tx


@dataclass
class Events:
    first_connected: list[VpnClient] = field(default_factory=list)
    expiring: list[VpnClient] = field(default_factory=list)


def _day(now: datetime) -> str:
    # The local day (TZ, like the scheduler): "today" ends at the owner's midnight, not UTC's.
    return now.astimezone().strftime("%Y-%m-%d")


def delta(previous: int | None, current: int) -> int:
    """Growth of a kernel counter; a smaller value means it restarted from zero."""
    if previous is None or current < previous:
        return current
    return current - previous


async def snapshot(clients: list[VpnClient], now: datetime | None = None) -> Events:
    """Fold the current counters into the totals; return what the owner should hear about."""
    now = now or datetime.now(UTC)
    events = Events()
    async with sql.session() as s:
        for client in clients:
            state = await s.get(ClientState, client.id)
            known = state is not None
            if state is None:
                state = ClientState(id=client.id)
                s.add(state)
            rx = delta(state.last_rx, client.rx)
            tx = delta(state.last_tx, client.tx)
            state.name, state.ipv4 = client.name, client.ipv4
            state.last_rx, state.last_tx = client.rx, client.tx
            state.total_rx = int(state.total_rx or 0) + rx
            state.total_tx = int(state.total_tx or 0) + tx
            state.seen_at = now
            if client.latest_handshake and not state.first_connected_at:
                state.first_connected_at = client.latest_handshake
                known_since_creation = known or (
                    client.created_at is not None and now - client.created_at <= FIRST_CONNECT_WINDOW
                )
                if known_since_creation:
                    events.first_connected.append(client)
            # A string: stored datetimes come back without a timezone, and a naive one never
            # equals the aware one from wg-easy — the notice would repeat every snapshot.
            if (
                client.expires_at
                and client.enabled
                and now < client.expires_at <= now + EXPIRY_NOTICE
                and state.expiry_noticed_for != client.expires_at.isoformat()
            ):
                state.expiry_noticed_for = client.expires_at.isoformat()
                events.expiring.append(client)
            if rx or tx:
                day = await s.get(TrafficDay, (client.id, _day(now)))
                if day is None:
                    s.add(TrafficDay(client_id=client.id, day=_day(now), rx=rx, tx=tx))
                else:
                    day.rx += rx
                    day.tx += tx
        await s.commit()
    return events


async def totals(client_ids: list[int]) -> dict[int, Totals]:
    """Traffic since the client was created, across counter restarts. Empty when the DB is down."""
    result = {client_id: Totals() for client_id in client_ids}
    try:
        async with sql.session() as s:
            for row in await s.scalars(select(ClientState).where(ClientState.id.in_(client_ids))):
                result[row.id] = Totals(int(row.total_rx or 0), int(row.total_tx or 0))
    except Exception as e:
        logger.warning("VPN totals unavailable (DB): %s", e)
    return result


async def period(client_ids: list[int], days: int, now: datetime | None = None) -> dict[int, Totals]:
    """Traffic over the last `days` days, today included."""
    now = now or datetime.now(UTC)
    first = _day(now - timedelta(days=days - 1))
    result = {client_id: Totals() for client_id in client_ids}
    try:
        async with sql.session() as s:
            query = select(TrafficDay).where(TrafficDay.client_id.in_(client_ids), TrafficDay.day >= first)
            for row in await s.scalars(query):
                entry = result.setdefault(row.client_id, Totals())
                entry.rx += int(row.rx or 0)
                entry.tx += int(row.tx or 0)
    except Exception as e:
        logger.warning("VPN traffic history unavailable (DB): %s", e)
    return result


async def forget(client_id: int) -> None:
    try:
        async with sql.session() as s:
            await s.execute(delete(ClientState).where(ClientState.id == client_id))
            await s.execute(delete(TrafficDay).where(TrafficDay.client_id == client_id))
            await s.commit()
    except Exception as e:
        # The peer is already gone from wg-easy; stale history only costs a few rows.
        logger.warning("Could not forget VPN client %s history: %s", client_id, e)
