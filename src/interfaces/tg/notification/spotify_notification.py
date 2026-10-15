"""Spotify family notices: new top-ups and charges as they come, reminders on schedule.

Every reminder is claimed in ``spotify_notices`` before it is sent, so a restart, the
webhook and the poll seeing the same charge, or the evening run repeating the morning's
never send anything twice. A member who never opened the bot cannot be written to: the
owner's report names them instead.
"""

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from src.config import settings
from src.db.sql import session
from src.interfaces.tg.formatters import spotify as fmt
from src.interfaces.tg.keyboards.spotify import get_pay_kb, get_spotify_sender_kb
from src.services.spotify import ledger, monobank, repo, schedule, sync
from src.services.spotify.models import Charge, Member
from src.services.spotify.report import Snapshot, snapshot, today, tz

logger = logging.getLogger("tg.notification.spotify")


async def _to_member(bot: Bot, member: Member, text: str, snap: Snapshot, amount: int = 0) -> bool:
    """True if delivered. Not linked or blocked the bot — False, the owner hears about it."""
    if not member.tg_id or member.is_owner:
        return False
    try:
        await bot.send_message(member.tg_id, text, reply_markup=get_pay_kb(snap.pay_url(amount)))
        return True
    except TelegramAPIError as e:
        logger.info("Could not write to %s: %s", member.name, e)
        return False


async def _to_owner(bot: Bot, text: str, quiet: bool = False, **kwargs) -> None:
    try:
        await bot.send_message(settings.telegram_admin_id, text, disable_notification=quiet, **kwargs)
    except TelegramAPIError as e:  # one failed message must not drop the rest of the batch
        logger.warning("Could not write to the owner: %s", e)


# ── As things happen ─────────────────────────────────────────────────────────


async def handle(bot: Bot, result: sync.Ingested) -> None:
    """New items from the webhook or the poll → the people concerned."""
    if not (result.topups or result.unknown or result.charges):
        return
    snap = await snapshot()
    by_id = {m.id: m for m in snap.members}
    for transaction in result.topups:
        member = by_id.get(transaction.member_id or 0)
        if member is None:
            continue
        if not member.is_owner:
            await _to_member(bot, member, fmt.notice_topup(snap, member, transaction.amount), snap)
        await _to_owner(bot, fmt.notice_topup_owner(member, transaction, snap), quiet=True)
    for transaction in result.unknown:
        await _to_owner(
            bot,
            fmt.notice_unknown(transaction),
            reply_markup=get_spotify_sender_kb(transaction.sender or "", snap.members, back=False),
        )
    for charge in result.charges:
        if charge.amount > 0:
            await after_charge(bot, charge)


async def after_charge(bot: Bot, charge: Charge) -> None:
    snap = await snapshot(money=False)
    async with session() as s, s.begin():
        if not await repo.claim_notice(s, 0, "charge", charge.id):
            return
        earlier = [c for c in snap.charges if c.amount > 0 and c.time < charge.time]
        claims = {m.id: await repo.claim_notice(s, m.id, "debt0", charge.id) for m in snap.members}
    previous = earlier[-1].operation_amount if earlier else None
    changed = previous if previous is not None and previous != charge.operation_amount else None
    await _to_owner(bot, fmt.notice_owner_charge(snap, charge, changed))
    for member in _debtors(snap):
        if claims.get(member.id):
            await _to_member(bot, member, fmt.notice_debt(snap, member, charge), snap, -snap.book[member.id].balance)


def _debtors(snap: Snapshot) -> list[Member]:
    return [m for m in snap.members if not m.is_owner and not m.left_on and snap.book[m.id].balance < 0]


def _short(snap: Snapshot) -> list[Member]:
    """Members whose balance does not cover the next share."""
    return [
        m
        for m in snap.members
        if not m.is_owner and snap.share(m) and ledger.to_pay(snap.book[m.id].balance, snap.share(m)) > 0
    ]


# ── On schedule ──────────────────────────────────────────────────────────────


async def spotify_poll(bot: Bot) -> None:
    """Hourly: whatever the webhook missed."""
    if not monobank.configured():
        return
    try:
        result = await sync.poll()
    except monobank.MonobankError as e:
        logger.warning("Spotify poll skipped: %s", e)
        return
    except Exception:
        logger.exception("Spotify poll failed")
        return
    try:
        await handle(bot, result)
    except Exception:
        logger.exception("Spotify notices failed")


async def spotify_tick(bot: Bot, slot: str) -> None:
    """10:00 and 18:00: reminders before the charge, the follow-up to debtors after it."""
    if not monobank.configured():
        return
    try:
        snap = await snapshot(money=True)
    except Exception:
        logger.exception("Spotify reminders skipped")
        return
    if not snap.configured or not snap.upcoming:
        return
    last = snap.last_charge
    last_day = ledger.local_day(last.time, tz()) if last else None
    actions = schedule.due(today(), slot, snap.upcoming.day, last_day)
    if "before" in actions:
        await remind_before(bot, snap, f"{snap.upcoming.day}-{slot}")
    if "debt" in actions and last:
        await remind_debtors(bot, snap, f"{last.id}-3")


async def remind_before(bot: Bot, snap: Snapshot, period: str, force: bool = False) -> list[Member]:
    """Members short of the next share; returns those it could not reach."""
    short = _short(snap)
    missed = []
    async with session() as s, s.begin():
        claims = {m.id: force or await repo.claim_notice(s, m.id, "before", period) for m in short}
        owner_claim = force or await repo.claim_notice(s, 0, "before", period)
    for member in short:
        if not claims[member.id] or not member.notify:
            continue
        amount = ledger.to_pay(snap.book[member.id].balance, snap.share(member))
        if not await _to_member(bot, member, fmt.notice_before(snap, member), snap, amount):
            missed.append(member)
    if owner_claim:
        text = fmt.notice_owner_before(snap, short)
        if missed:
            text += "\n⚠️ Не смог написать: " + ", ".join(escape(m.name) for m in missed) + " — перешли сам."
        await _to_owner(bot, text)
    return missed


async def remind_debtors(bot: Bot, snap: Snapshot, period: str, force: bool = False) -> tuple[int, list[Member]]:
    """(sent, unreachable) — the follow-up after the charge, or the owner's button."""
    sent, missed = 0, []
    debtors = _debtors(snap) or (_short(snap) if force else [])
    async with session() as s, s.begin():
        claims = {m.id: force or await repo.claim_notice(s, m.id, "debt", period) for m in debtors}
    for member in debtors:
        if not claims[member.id] or (not member.notify and not force):
            continue
        balance = snap.book[member.id].balance
        if balance < 0:
            text, amount = fmt.notice_debt(snap, member, None), -balance
        else:
            text, amount = fmt.notice_before(snap, member), ledger.to_pay(balance, snap.share(member))
        if await _to_member(bot, member, text, snap, amount):
            sent += 1
        else:
            missed.append(member)
    return sent, missed


async def remind_one(bot: Bot, member: Member) -> bool:
    snap = await snapshot()
    account = snap.book[member.id]
    share = snap.share(member)
    if account.balance < 0:
        return await _to_member(bot, member, fmt.notice_debt(snap, member, None), snap, -account.balance)
    if snap.upcoming and share:
        return await _to_member(
            bot, member, fmt.notice_before(snap, member), snap, ledger.to_pay(account.balance, share)
        )
    return await _to_member(bot, member, fmt.notice_status(snap, member), snap)


async def ensure_webhook(bot: Bot) -> None:
    """Point Monobank's webhook at the bot once; the URL is remembered, a change re-sets it."""
    if not (monobank.configured() and settings.monobank_webhook_secret) or settings.debug:
        return
    url = sync.webhook_url()
    try:
        info = await monobank.client_info(fresh=True)
        if info.get("webHookUrl") == url:
            return
        await monobank.set_webhook(url)
        logger.info("Monobank webhook set")
    except monobank.MonobankError as e:
        logger.warning("Monobank webhook not set: %s", e)
        await _to_owner(bot, f"🎧 Не смог подключить вебхук Monobank: {e}. Работаю опросом раз в час.", quiet=True)
