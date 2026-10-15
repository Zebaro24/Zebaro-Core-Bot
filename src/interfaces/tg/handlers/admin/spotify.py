"""/spotify for the owner: the family plan's table, members, corrections, setup."""

import asyncio
import logging
import re
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.service_manager import ServiceManager
from src.db.sql import session
from src.interfaces.tg.formatters import spotify as fmt
from src.interfaces.tg.keyboards.spotify import (
    SpotifyCallback,
    get_spotify_back_kb,
    get_spotify_cancel_kb,
    get_spotify_confirm_kb,
    get_spotify_home_kb,
    get_spotify_member_kb,
    get_spotify_sender_kb,
    get_spotify_senders_kb,
    get_spotify_setup_kb,
    sender_key,
)
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.interfaces.tg.notification import spotify_notification as notify
from src.interfaces.tg.rich import answer_rich, show_rich
from src.services.spotify import ledger, monobank, repo, sync
from src.services.spotify.models import JarTransaction, Member
from src.services.spotify.report import snapshot, today, tz

logger = logging.getLogger("tg.handlers.admin.spotify")

router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())

NAME_MAX = 40
# Strong references to the history reloads in flight (the loop keeps only weak ones).
_reloads: set[asyncio.Task[None]] = set()


class SpotifyForm(StatesGroup):
    adjust = State()
    add = State()
    rename = State()
    joined = State()
    reload = State()


_FORM_TEXT = F.text & ~F.text.startswith("/")
_AMOUNT = re.compile(r"^\s*([+\-−]?)\s*(\d+(?:[.,]\d{1,2})?)\s*(.*)$", re.DOTALL)


def parse_adjustment(text: str) -> tuple[int, str] | None:
    """ "+300 перевёл на карту" → (30000, "перевёл на карту"); "-50,5" → (-5050, "")."""
    match = _AMOUNT.match(text)
    if not match:
        return None
    sign, number, note = match.groups()
    kopecks = round(float(number.replace(",", ".")) * 100)
    if kopecks == 0:
        return None
    return (-kopecks if sign in ("-", "−") else kopecks), note.strip()[:256]


def parse_day(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _service_off() -> bool:
    return not ServiceManager.get_instance().is_service_enabled("spotify")


async def _home(message: Message, edit: bool = True) -> None:
    snap = await snapshot(money=True)
    html, kb = fmt.format_overview(snap), get_spotify_home_kb(snap.members, snap.configured)
    await (show_rich(message, html, kb) if edit else answer_rich(message, html, kb))


async def _member_screen(message: Message, member_id: int) -> None:
    snap = await snapshot()
    async with session() as s:
        member = await s.get(Member, member_id)
        if member is None:
            await message.answer("Такого участника больше нет.")
            return
        transactions = await repo.transactions(s, member_id)
        adjustments = await repo.adjustments(s, member_id)
    await show_rich(
        message, fmt.format_member_card(snap, member, transactions, adjustments), get_spotify_member_kb(member)
    )


async def _sender_name(key: str) -> str | None:
    async with session() as s:
        names = {name for name, _, _ in await repo.unknown_senders(s)} | set(await repo.aliases(s))
    return next((n for n in names if sender_key(n) == key), None)


# A sender whose first top-up came this soon after the plan's start was there from the start.
_FOUNDER_DAYS = 62


async def _join_day(s: AsyncSession, name: str) -> date:
    """When a member found in the jar joined: the plan's start for the founders, otherwise the
    day of their first top-up (a newcomer pays after joining, right after a charge)."""
    history = await repo.get_state(s, repo.HISTORY)
    first = await repo.first_topup(s, name)
    first_day = ledger.local_day(first, tz()) if first else today()
    if history:
        since = date.fromisoformat(history["since"])
        if (first_day - since).days <= _FOUNDER_DAYS:
            return since
    return first_day


async def _invite_link(bot: Bot, member: Member) -> str:
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start=sp_{member.invite_code}"


async def _active_count() -> int:
    async with session() as s:
        return sum(1 for m in await repo.members(s) if not m.left_on)


@router.message(Command("spotify"))
async def spotify_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    if _service_off():
        await message.answer("🎧 Spotify выключен — включи его в /services.")
        return
    if not monobank.configured():
        await message.answer("🎧 Нет MONOBANK_TOKEN в окружении бота.")
        return
    await _home(message, edit=False)


@router.callback_query(SpotifyCallback.filter())
async def spotify_callback(query: CallbackQuery, callback_data: SpotifyCallback, state: FSMContext, bot: Bot) -> None:
    message = query.message
    if not isinstance(message, Message):
        await query.answer()
        return
    if _service_off():
        await query.answer("🎧 Spotify выключен — включи его в /services", show_alert=True)
        return
    action, member_id, arg = callback_data.action, callback_data.member_id, callback_data.arg
    notice: str | None = None
    try:
        notice = await _dispatch(query, message, state, bot, action, member_id, arg)
    except monobank.MonobankError as e:
        notice = f"Monobank не ответил: {e}"[:190]
    try:
        await query.answer(notice or None, show_alert=bool(notice and len(notice) > 60))
    except TelegramBadRequest:
        pass  # answered already ("🔄 Читаю выписку…"), or too late after a long poll


async def _dispatch(
    query: CallbackQuery, message: Message, state: FSMContext, bot: Bot, action: str, member_id: int, arg: str
) -> str | None:
    if action == "home":
        await state.clear()
        await _home(message)
    elif action == "sync":
        await query.answer("🔄 Читаю выписку — до двух минут…")
        await notify.handle(bot, await sync.poll())
        await _home(message)
    elif action == "stats":
        await show_rich(message, fmt.format_stats(await snapshot()), get_spotify_back_kb())
    elif action == "member":
        await state.clear()
        await _member_screen(message, member_id)
    elif action == "adjust":
        await state.set_state(SpotifyForm.adjust)
        await state.update_data(member_id=member_id)
        await message.answer(
            "Сумма и за что: <code>+300 перевёл на карту</code> — засчитать как оплату, "
            "<code>-120 долг за 2023</code> — записать в долг. Видно в истории с 📝.",
            reply_markup=get_spotify_cancel_kb(member_id),
        )
    elif action == "rename":
        await state.set_state(SpotifyForm.rename)
        await state.update_data(member_id=member_id)
        await message.answer("Новое имя:", reply_markup=get_spotify_cancel_kb(member_id))
    elif action == "joined":
        await state.set_state(SpotifyForm.joined)
        await state.update_data(member_id=member_id)
        await message.answer(
            "С какого дня человек в подписке? <code>ДД.ММ.ГГГГ</code> — его доля считается со "
            "списаний начиная с этого дня. Балансы пересчитаются.",
            reply_markup=get_spotify_cancel_kb(member_id),
        )
    elif action == "add":
        if await _active_count() >= ledger.MAX_MEMBERS:
            return f"В семейной подписке максимум {ledger.MAX_MEMBERS} — сначала отметь, кто вышел."
        await state.set_state(SpotifyForm.add)
        await message.answer(
            "Имя нового участника. Он в доле со следующего списания, поэтому лучше добавлять "
            "сразу после 12-го. Как в Monobank его зовут, бот узнает сам по первому пополнению.",
            reply_markup=get_spotify_cancel_kb(),
        )
    elif action == "invite":
        async with session() as s:
            member = await s.get(Member, member_id)
        if member:
            await message.answer(
                f"Ссылка для <b>{member.name}</b> — перешли её, человек нажмёт «Start» и будет получать "
                f"напоминания:\n{await _invite_link(bot, member)}"
            )
    elif action in ("notify_on", "notify_off"):
        async with session() as s, s.begin():
            member = await s.get(Member, member_id)
            if member:
                member.notify = action == "notify_on"
        await _member_screen(message, member_id)
    elif action == "remind":
        async with session() as s:
            member = await s.get(Member, member_id)
        if member is None:
            return None
        if member.is_owner:
            return "Себе напоминать не нужно 🙂"
        return "🔔 Отправил" if await notify.remind_one(bot, member) else "⚠️ Не подключён к боту — перешли приглашение"
    elif action == "remind_all":
        snap = await snapshot()
        sent, missed = await notify.remind_debtors(bot, snap, "manual", force=True)
        text = f"🔔 Напомнил: {sent}"
        if missed:
            text += f". Не дошло: {', '.join(m.name for m in missed)}"
        return text if sent or missed else "Должников нет — все оплатили ✅"
    elif action == "leave":
        await message.edit_reply_markup(
            reply_markup=get_spotify_confirm_kb("leave_yes", member_id, "🚪 Да, вышел сегодня")
        )
        return "Лучше сразу после списания: доля за этот месяц уже начислена"
    elif action == "leave_yes":
        async with session() as s, s.begin():
            member = await s.get(Member, member_id)
            if member:
                member.left_on = today()
        snap = await snapshot()
        if member:
            await message.answer(fmt.notice_leave(snap, member))
        await _member_screen(message, member_id)
    elif action == "rejoin":
        if await _active_count() >= ledger.MAX_MEMBERS:
            return f"В семейной подписке уже {ledger.MAX_MEMBERS}"
        async with session() as s, s.begin():
            member = await s.get(Member, member_id)
            if member:
                member.left_on = None
        await _member_screen(message, member_id)
    elif action == "senders":
        async with session() as s:
            senders = await repo.unknown_senders(s)
        await show_rich(message, fmt.format_senders(senders), get_spotify_senders_kb([n for n, _, _ in senders]))
    elif action == "sender":
        name = await _sender_name(arg)
        if name is None:
            return "Этот отправитель уже разобран"
        async with session() as s:
            members = await repo.members(s)
        await message.edit_reply_markup(reply_markup=get_spotify_sender_kb(name, members))
    elif action in ("sender_to", "sender_new", "sender_skip"):
        return await _resolve_sender(message, action, member_id, arg)
    elif action == "setup":
        await _setup(message)
    elif action in ("set_jar", "set_card"):
        info = await monobank.client_info()
        account = next((a for a in monobank.parse_accounts(info) if a.id == arg), None)
        if account:
            async with session() as s, s.begin():
                if action == "set_jar":
                    await repo.set_state(s, repo.JAR, account.id)
                    await repo.set_state(s, repo.JAR_SEND, account.send_id)
                else:
                    await repo.set_state(s, repo.CARD, account.id)
                if not await repo.owner(s):
                    await repo.add_member(s, "Я", today(), is_owner=True)
        await _setup(message)
    elif action == "webhook":
        await notify.ensure_webhook(bot)
        info = await monobank.client_info(fresh=True)
        return "🪝 Вебхук подключён" if info.get("webHookUrl") == sync.webhook_url() else "🪝 Не подключился — см. логи"
    elif action == "reload":
        await state.set_state(SpotifyForm.reload)
        await message.answer(
            "С какой даты загрузить всю историю банки и списаний? <code>ДД.ММ.ГГГГ</code> — день "
            "первого списания Spotify. Это долго: Monobank отдаёт месяц выписки в минуту.",
            reply_markup=get_spotify_cancel_kb(),
        )
    return None


async def _setup(message: Message) -> None:
    info = await monobank.client_info()
    async with session() as s:
        jar_id, card_id = await repo.get_state(s, repo.JAR), await repo.get_state(s, repo.CARD)
        history = await repo.get_state(s, repo.HISTORY)
    loaded = f"История загружена с {history['since']}." if history else "История ещё не загружена."
    html = (
        "<h3>⚙️ Spotify · настройка</h3>"
        "<p>Выбери банку, куда скидываются, и карту, с которой платится Spotify. "
        f"{loaded}</p>"
    )
    await show_rich(message, html, get_spotify_setup_kb(monobank.parse_accounts(info), jar_id, card_id))


async def _resolve_sender(message: Message, action: str, member_id: int, key: str) -> str | None:
    name = await _sender_name(key)
    if name is None:
        return "Этот отправитель уже разобран"
    async with session() as s, s.begin():
        if action == "sender_skip":
            await repo.assign_alias(s, name, None)
            text = f"🚫 {name} — не учитываю"
        elif action == "sender_new":
            members = [m for m in await repo.members(s) if not m.left_on]
            if len(members) >= ledger.MAX_MEMBERS:
                return f"В подписке уже {ledger.MAX_MEMBERS} — сначала отметь, кто вышел"
            joined = await _join_day(s, name)
            member = await repo.add_member(s, name, joined, alias=name)
            text = f"➕ {member.name} — участник с {joined:%d.%m.%Y}"
        else:
            member_obj = await s.get(Member, member_id)
            if member_obj is None:
                return "Такого участника нет"
            await repo.assign_alias(s, name, member_id)
            text = f"✅ {name} → {member_obj.name}"
        rest = await repo.unknown_senders(s)
    await message.edit_text(f"{message.html_text}\n\n{text}") if message.text else None
    if rest and message.rich_message is not None:
        await show_rich(message, fmt.format_senders(rest), get_spotify_senders_kb([n for n, _, _ in rest]))
    return text


# ── Forms ────────────────────────────────────────────────────────────────────


@router.message(SpotifyForm.adjust, _FORM_TEXT)
async def adjust_form(message: Message, state: FSMContext) -> None:
    parsed = parse_adjustment(message.text or "")
    member_id = (await state.get_data()).get("member_id", 0)
    if parsed is None:
        await message.answer(
            "Не понял сумму. Пример: <code>+300 перевёл на карту</code>", reply_markup=get_spotify_cancel_kb(member_id)
        )
        return
    amount, note = parsed
    async with session() as s, s.begin():
        await repo.add_adjustment(s, member_id, amount, note)
    await state.clear()
    await message.answer(f"📝 Записал {fmt.uah(amount, sign=True)}" + (f" · {note}" if note else ""))
    sent = await message.answer("…")
    await _member_screen(sent, member_id)


@router.message(SpotifyForm.rename, _FORM_TEXT)
async def rename_form(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:NAME_MAX]
    member_id = (await state.get_data()).get("member_id", 0)
    async with session() as s, s.begin():
        member = await s.get(Member, member_id)
        if member and name:
            member.name = name
    await state.clear()
    sent = await message.answer("…")
    await _member_screen(sent, member_id)


@router.message(SpotifyForm.joined, _FORM_TEXT)
async def joined_form(message: Message, state: FSMContext) -> None:
    member_id = (await state.get_data()).get("member_id", 0)
    joined = parse_day(message.text or "")
    if joined is None:
        await message.answer("Дата как <code>12.09.2022</code>", reply_markup=get_spotify_cancel_kb(member_id))
        return
    async with session() as s, s.begin():
        member = await s.get(Member, member_id)
        if member:
            member.joined_on = joined
    await state.clear()
    sent = await message.answer("…")
    await _member_screen(sent, member_id)


@router.message(SpotifyForm.add, _FORM_TEXT)
async def add_form(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:NAME_MAX]
    if not name:
        return
    async with session() as s, s.begin():
        member = await repo.add_member(s, name, today())
    await state.clear()
    await message.answer(f"➕ {member.name} в подписке с сегодняшнего дня.")
    sent = await message.answer("…")
    await _member_screen(sent, member.id)


@router.message(SpotifyForm.reload, _FORM_TEXT)
async def reload_form(message: Message, state: FSMContext, bot: Bot) -> None:
    since = parse_day(message.text or "")
    if since is None or since > today():
        await message.answer("Дата как <code>12.09.2022</code>", reply_markup=get_spotify_cancel_kb())
        return
    await state.clear()
    months = max(1, (today() - since).days // 31 + 1)
    await message.answer(f"📥 Загружаю с {since:%d.%m.%Y}: ~{months * 2} мин. Напишу, когда закончу.")
    task = asyncio.create_task(_reload(bot, since))
    _reloads.add(task)
    task.add_done_callback(_reloads.discard)


async def _reload(bot: Bot, since: date) -> None:
    try:
        async with session() as s, s.begin():
            owner = await repo.owner(s)
            if owner and owner.joined_on > since:
                owner.joined_on = since
        result = await sync.reload_history(since)
    except Exception as e:
        logger.exception("History reload failed")
        await bot.send_message(message_owner(), f"📥 Загрузка истории оборвалась: {e}")
        return
    async with session() as s:
        senders = await repo.unknown_senders(s)
        transactions: list[JarTransaction] = await repo.transactions(s)
    paid = sum(c.amount for c in result.charges)
    await bot.send_message(
        message_owner(),
        f"📥 Готово: {len(transactions)} операций банки, {len(result.charges)} списаний Spotify на "
        f"{fmt.uah(paid)}. Неразобранных отправителей: {len(senders)} — /spotify → «👥 Отправители».",
    )


def message_owner() -> int:
    return int(settings.telegram_admin_id)
