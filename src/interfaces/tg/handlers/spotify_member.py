"""The family plan for its members: the invite link, /spotify with their own balance.

Included before the admin routers and /start: the admin router answers "ты не админ" to
everyone else, and a plain /start would swallow the invite's ``sp_<code>`` payload.
"""

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, InlineKeyboardMarkup, Message

from src.config import settings
from src.core.service_manager import ServiceManager
from src.db.sql import session
from src.interfaces.tg.commands import EVERYONE
from src.interfaces.tg.formatters import spotify as fmt
from src.interfaces.tg.keyboards.spotify import SpotifyMemberCallback, get_my_spotify_kb
from src.interfaces.tg.rich import answer_rich, show_rich
from src.services.spotify import ledger, repo
from src.services.spotify.models import Member
from src.services.spotify.report import snapshot

logger = logging.getLogger("tg.handlers.spotify_member")

router = Router()

INVITE_PREFIX = "sp_"
MEMBER_MENU = [*EVERYONE, BotCommand(command="spotify", description="Spotify Family: мой баланс")]


def _not_owner(event: Message | CallbackQuery) -> bool:
    return event.from_user is not None and event.from_user.id != settings.telegram_admin_id


def _service_on() -> bool:
    return ServiceManager.get_instance().is_service_enabled("spotify")


async def _my_screen(member: Member) -> tuple[str, InlineKeyboardMarkup]:
    snap = await snapshot()
    async with session() as s:
        transactions = await repo.transactions(s, member.id)
        adjustments = await repo.adjustments(s, member.id)
    pay = ledger.to_pay(snap.book[member.id].balance, snap.share(member))
    html = fmt.format_my_card(snap, member, transactions, adjustments)
    return html, get_my_spotify_kb(member, snap.pay_url(pay))


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(INVITE_PREFIX)))
async def invite(message: Message, command: CommandObject, bot: Bot) -> None:
    user = message.from_user
    code = (command.args or "")[len(INVITE_PREFIX) :]
    if user is None or not _service_on():
        return
    async with session() as s, s.begin():
        member = await repo.member_by_invite(s, code)
        if member is None or member.left_on:
            await message.answer("🎧 Ссылка не действует — попроси новую.")
            return
        taken = await repo.member_by_tg(s, user.id)
        if taken and taken.id != member.id:
            taken.tg_id = None
            await s.flush()  # SQLite checks UNIQUE(tg_id) row by row: free it first
        member.tg_id = user.id
        member.invite_code = repo.new_invite_code()  # one link — one person
        name = member.name
    logger.info("Spotify member %s linked to user_id=%s", name, user.id)
    try:
        await bot.set_my_commands(MEMBER_MENU, scope=BotCommandScopeChat(chat_id=user.id))
    except Exception as e:
        logger.info("Could not set the member menu: %s", e)
    await message.answer(
        f"🎧 Привет, {escape(name)}! Теперь я напомню перед списанием Spotify Family (12-го) и скажу, "
        "когда твой перевод дошёл. Баланс в любой момент — /spotify."
    )
    await bot.send_message(
        settings.telegram_admin_id, f"🔗 {escape(name)} подключился к боту.", disable_notification=True
    )
    async with session() as s:
        linked = await s.get(Member, member.id)
    if linked:
        html, kb = await _my_screen(linked)
        await answer_rich(message, html, kb)


@router.message(Command("spotify"), _not_owner)
async def my_spotify(message: Message) -> None:
    if message.from_user is None or not _service_on():
        return
    async with session() as s:
        member = await repo.member_by_tg(s, message.from_user.id)
    if member is None:
        await message.answer("🎧 Ты не в семейной подписке. Если это ошибка — попроси ссылку-приглашение.")
        return
    html, kb = await _my_screen(member)
    await answer_rich(message, html, kb)


@router.callback_query(SpotifyMemberCallback.filter())
async def my_spotify_callback(query: CallbackQuery, callback_data: SpotifyMemberCallback) -> None:
    message = query.message
    if not isinstance(message, Message) or not _service_on():
        await query.answer()
        return
    async with session() as s, s.begin():
        member = await repo.member_by_tg(s, query.from_user.id)
        if member and callback_data.action in ("notify_on", "notify_off"):
            member.notify = callback_data.action == "notify_on"
    if member is None:
        await query.answer("Ты не в семейной подписке", show_alert=True)
        return
    html, kb = await _my_screen(member)
    await show_rich(message, html, kb)
    await query.answer("🔕 Напоминания выключены" if not member.notify else None)
