"""Monobank → the tables: the webhook's single items, the hourly poll, the full reload.

All three go through ``ingest``: an item already stored is updated in place (a hold that
settled), never counted twice, so the webhook and the poll may overlap freely.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.sql import session
from src.services.spotify import monobank, repo
from src.services.spotify.models import Charge, JarTransaction

logger = logging.getLogger("services.spotify.sync")

SENDER_PREFIX = "Від:"
SPOTIFY = "spotify"
TRANSFER_MCC = 4829  # money transfer: card↔jar, person to person
# The poll re-reads the last hour: an item may show up in the statement a bit late.
OVERLAP = 3600
FIRST_POLL = 31 * 86400
# A charge seen within a day of it: today's rate is its rate, good enough to measure the markup.
LIVE = 86400


@dataclass
class Ingested:
    topups: list[JarTransaction] = field(default_factory=list)  # new, someone's
    unknown: list[JarTransaction] = field(default_factory=list)  # new, sender not known yet
    charges: list[Charge] = field(default_factory=list)  # new Spotify payments

    def extend(self, other: "Ingested") -> None:
        self.topups += other.topups
        self.unknown += other.unknown
        self.charges += other.charges


def classify(item: dict) -> tuple[str, str | None]:
    """(kind, sender) of a jar item: "Від: Name" is someone's top-up."""
    description = (item.get("description") or "").strip()
    if item["amount"] < 0:
        return "withdrawal", None
    if description.startswith(SENDER_PREFIX):
        return "topup", description[len(SENDER_PREFIX) :].strip() or None
    return "own", None


def is_spotify(item: dict) -> bool:
    """A payment to Spotify — not a card↔jar transfer whose text names a "Spotify" jar."""
    return SPOTIFY in (item.get("description") or "").lower() and item.get("mcc") != TRANSFER_MCC


async def ingest(s: AsyncSession, account: str, items: list[dict]) -> Ingested:
    jar = await repo.get_state(s, repo.JAR)
    card = await repo.get_state(s, repo.CARD)
    result = Ingested()
    if account == jar:
        known = await repo.aliases(s)
        owner = await repo.owner(s)
        for item in items:
            await _jar_item(s, item, known, owner.id if owner else None, result)
    elif account == card:
        for item in items:
            if is_spotify(item):
                await _card_item(s, item, result)
    await s.flush()
    return result


async def _jar_item(
    s: AsyncSession, item: dict, known: dict[str, int | None], owner_id: int | None, result: Ingested
) -> None:
    kind, sender = classify(item)
    row = await s.get(JarTransaction, item["id"])
    fresh = row is None
    if row is None:
        row = JarTransaction(id=item["id"], kind=kind, sender=sender)
        if kind == "own":
            row.member_id = owner_id
        elif sender in known:
            row.member_id = known[sender]
        s.add(row)
    row.time = item["time"]
    row.amount = item["amount"]
    row.balance = item.get("balance", 0)
    row.description = (item.get("description") or "")[:256]
    row.comment = (item.get("comment") or "")[:512]
    if fresh and kind == "topup":
        if sender in known:
            if row.member_id is not None:
                result.topups.append(row)
        else:
            result.unknown.append(row)


async def _card_item(s: AsyncSession, item: dict, result: Ingested) -> None:
    row = await s.get(Charge, item["id"])
    fresh = row is None
    if row is None:
        row = Charge(id=item["id"])
        s.add(row)
    row.time = item["time"]
    row.amount = -item["amount"]  # a payment is negative on the card, a refund positive
    row.operation_amount = -item.get("operationAmount", item["amount"])
    row.currency_code = item.get("currencyCode", monobank.UAH)
    if fresh:
        if row.currency_code != monobank.UAH and abs(time.time() - row.time) < LIVE:
            try:
                row.rate = await monobank.rate(row.currency_code)
            except monobank.MonobankError as e:
                logger.info("No rate for the new charge: %s", e)
        result.charges.append(row)


async def poll() -> Ingested:
    """Both accounts from the cursor to now. Slow: each statement window waits a minute."""
    async with session() as s:
        jar, card = await repo.get_state(s, repo.JAR), await repo.get_state(s, repo.CARD)
        cursor = await repo.get_state(s, repo.CURSOR)
    if not (jar and card):
        return Ingested()
    now = int(time.time())
    start = (cursor - OVERLAP) if cursor else now - FIRST_POLL
    result = Ingested()
    for account in (jar, card):
        try:
            items = await monobank.statement(account, start, now)
            async with session() as s, s.begin():
                result.extend(await ingest(s, account, items))
        except Exception:
            # What is stored is announced; the cursor stays, the next poll retries the rest.
            logger.exception("Poll of %s failed", account)
            return result
    async with session() as s, s.begin():
        await repo.set_state(s, repo.CURSOR, now)
    return result


async def reload_history(since: date) -> Ingested:
    """Everything from `since`: the first fill and the "пересчитать всё" button."""
    async with session() as s:
        jar, card = await repo.get_state(s, repo.JAR), await repo.get_state(s, repo.CARD)
    if not (jar and card):
        return Ingested()
    start = int(datetime(since.year, since.month, since.day).timestamp())
    now = int(time.time())
    result = Ingested()
    for account in (jar, card):
        items = await monobank.statement(account, start, now)
        async with session() as s, s.begin():
            result.extend(await ingest(s, account, items))
        logger.info("History of %s since %s: %d items", account, since, len(items))
    async with session() as s, s.begin():
        await repo.set_state(s, repo.CURSOR, now)
        await repo.set_state(s, repo.HISTORY, {"since": since.isoformat(), "done": now})
    return result


def webhook_url() -> str:
    return f"{settings.webhook_url.rstrip('/')}/webhook/monobank/{settings.monobank_webhook_secret}"
