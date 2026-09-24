"""Traffic history and the notices that come from watching the VPN.

WireGuard's transfer counters live in the kernel and start from zero whenever the interface
restarts (a container restart, a reboot). A snapshot every few minutes turns them into running
totals that survive that, and into per-day traffic for "today" and "this week".
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.db.client import vpn_clients_collection, vpn_daily_collection
from src.services.vpn.client import VpnClient

logger = logging.getLogger("vpn.traffic")

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
    for client in clients:
        state: dict[str, Any] = await vpn_clients_collection.find_one({"_id": client.id}) or {}
        rx = delta(state.get("last_rx"), client.rx)
        tx = delta(state.get("last_tx"), client.tx)
        update: dict[str, Any] = {
            "name": client.name,
            "ipv4": client.ipv4,
            "last_rx": client.rx,
            "last_tx": client.tx,
            "total_rx": int(state.get("total_rx") or 0) + rx,
            "total_tx": int(state.get("total_tx") or 0) + tx,
            "seen_at": now,
        }
        if client.latest_handshake and not state.get("first_connected_at"):
            update["first_connected_at"] = client.latest_handshake
            known_since_creation = bool(state) or (
                client.created_at is not None and now - client.created_at <= FIRST_CONNECT_WINDOW
            )
            if known_since_creation:
                events.first_connected.append(client)
        if client.expires_at and client.enabled and now < client.expires_at <= now + EXPIRY_NOTICE:
            # A string: Mongo hands datetimes back without a timezone, and a naive one never
            # equals the aware one from wg-easy — the notice would repeat every snapshot.
            if state.get("expiry_noticed_for") != client.expires_at.isoformat():
                update["expiry_noticed_for"] = client.expires_at.isoformat()
                events.expiring.append(client)
        await vpn_clients_collection.update_one({"_id": client.id}, {"$set": update}, upsert=True)
        if rx or tx:
            await vpn_daily_collection.update_one(
                {"_id": f"{client.id}:{_day(now)}"},
                {"$inc": {"rx": rx, "tx": tx}, "$set": {"client_id": client.id, "day": _day(now)}},
                upsert=True,
            )
    return events


async def totals(client_ids: list[int]) -> dict[int, Totals]:
    """Traffic since the client was created, across counter restarts. Empty when Mongo is down."""
    result = {client_id: Totals() for client_id in client_ids}
    try:
        async for doc in vpn_clients_collection.find({"_id": {"$in": client_ids}}):
            result[doc["_id"]] = Totals(int(doc.get("total_rx") or 0), int(doc.get("total_tx") or 0))
    except Exception as e:
        logger.warning("VPN totals unavailable (DB): %s", e)
    return result


async def period(client_ids: list[int], days: int, now: datetime | None = None) -> dict[int, Totals]:
    """Traffic over the last `days` days, today included."""
    now = now or datetime.now(UTC)
    first = _day(now - timedelta(days=days - 1))
    result = {client_id: Totals() for client_id in client_ids}
    try:
        async for doc in vpn_daily_collection.find({"client_id": {"$in": client_ids}, "day": {"$gte": first}}):
            entry = result.setdefault(doc["client_id"], Totals())
            entry.rx += int(doc.get("rx") or 0)
            entry.tx += int(doc.get("tx") or 0)
    except Exception as e:
        logger.warning("VPN traffic history unavailable (DB): %s", e)
    return result


async def forget(client_id: int) -> None:
    try:
        await vpn_clients_collection.delete_one({"_id": client_id})
        await vpn_daily_collection.delete_many({"client_id": client_id})
    except Exception as e:
        # The peer is already gone from wg-easy; stale history only costs a few documents.
        logger.warning("Could not forget VPN client %s history: %s", client_id, e)
