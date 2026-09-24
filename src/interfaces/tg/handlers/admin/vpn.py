"""/vpn — the people on the WireGuard server: who is online, traffic, files, access."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaDocument, Message

from src.core.service_manager import ServiceManager
from src.interfaces.tg.formatters.vpn import exe_caption, files_caption, format_vpn_card, format_vpn_list
from src.interfaces.tg.keyboards.vpn import (
    VpnCallback,
    get_vpn_cancel_kb,
    get_vpn_card_kb,
    get_vpn_delete_kb,
    get_vpn_expiry_kb,
    get_vpn_list_kb,
)
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.interfaces.tg.rich import answer_rich, show_rich
from src.services.vpn import addressing, installer, traffic
from src.services.vpn.client import VpnClient, VpnError, WgEasy
from src.services.vpn.profiles import profiles

logger = logging.getLogger("tg.handlers.admin.vpn")

router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())

NAME_MAX = 40


class VpnForm(StatesGroup):
    new = State()
    rename = State()
    readdress = State()


def parse_new(text: str) -> tuple[str, int | None]:
    """ "Олена 18" → ("Олена", 18); "Олена Ковальчук" → ("Олена Ковальчук", None)."""
    words = text.split()
    if len(words) > 1 and words[-1].lstrip(".").isdecimal():
        return " ".join(words[:-1]), int(words[-1].lstrip("."))
    return " ".join(words), None


def _taken(clients: list[VpnClient], except_id: int | None = None) -> set[int]:
    return {c.host_number for c in clients if c.host_number is not None and c.id != except_id} | {addressing.SERVER}


async def _list_html(wg: WgEasy) -> tuple[str, list[VpnClient]]:
    clients = await wg.list_clients()
    week = await traffic.period([c.id for c in clients], days=7)
    return format_vpn_list(clients, week), clients


async def _card_html(wg: WgEasy, client_id: int) -> tuple[str, VpnClient]:
    client = await wg.get_client(client_id)
    ids = [client.id]
    today, week, overall = await asyncio.gather(
        traffic.period(ids, days=1), traffic.period(ids, days=7), traffic.totals(ids)
    )
    return format_vpn_card(client, today[client.id], week[client.id], overall[client.id]), client


def _service_off() -> bool:
    return not ServiceManager.get_instance().is_service_enabled("vpn")


# A command typed in the middle of a form is a command, not a name: "/services" sent while the
# bot waited for a name used to create a peer called "/services".
_FORM_TEXT = F.text & ~F.text.startswith("/")


@router.message(Command("vpn"))
async def vpn_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    if _service_off():
        await message.answer("🔐 Раздел VPN в боте выключен — включи его в /services (сам VPN работает).")
        return
    try:
        html, clients = await _list_html(WgEasy())
    except VpnError as e:
        await message.answer(f"🔐 Сервер VPN не отвечает: {e}")
        return
    await answer_rich(message, html, get_vpn_list_kb(clients))


@router.callback_query(VpnCallback.filter())
async def vpn_callback(query: CallbackQuery, callback_data: VpnCallback, state: FSMContext) -> None:
    message = query.message
    if not isinstance(message, Message):
        await query.answer()
        return
    if _service_off():
        await query.answer("🔐 VPN в боте выключен — включи его в /services", show_alert=True)
        return
    wg = WgEasy()
    action, client_id = callback_data.action, callback_data.client_id
    notice: str | None = None
    error: str | None
    answered = False
    try:
        if action == "exe":
            # Packing ~10 MB and uploading takes longer than Telegram waits for an answer.
            await query.answer("💾 Собираю установщик…")
            answered = True
            if problem := await send_exe(message, wg, client_id):
                await message.answer(problem)
        elif action == "list":
            await state.clear()
            html, clients = await _list_html(wg)
            await show_rich(message, html, get_vpn_list_kb(clients, callback_data.page))
        elif action == "card":
            await state.clear()
            html, client = await _card_html(wg, client_id)
            await show_rich(message, html, get_vpn_card_kb(client))
        elif action == "add":
            await state.set_state(VpnForm.new)
            await message.answer(
                "Как назвать? Имя и, если хочешь, номер адреса: <code>Олена 18</code> → 10.0.0.18.\n"
                "Без номера — первый свободный с .100. Мои устройства — .2–.9.",
                reply_markup=get_vpn_cancel_kb(),
            )
        elif action in ("enable", "disable"):
            await wg.set_enabled(client_id, action == "enable")
            notice = "▶️ Включён" if action == "enable" else "⏸️ Выключен — подключиться не сможет"
            html, client = await _card_html(wg, client_id)
            await show_rich(message, html, get_vpn_card_kb(client))
        elif action == "expiry_menu":
            client = await wg.get_client(client_id)
            await message.edit_reply_markup(reply_markup=get_vpn_expiry_kb(client))
        elif action == "expiry":
            notice = await _set_expiry(wg, client_id, callback_data.arg)
            html, client = await _card_html(wg, client_id)
            await show_rich(message, html, get_vpn_card_kb(client))
        elif action == "rename":
            await state.set_state(VpnForm.rename)
            await state.update_data(client_id=client_id)
            await message.answer("Новое имя:", reply_markup=get_vpn_cancel_kb(client_id))
        elif action == "readdress":
            await state.set_state(VpnForm.readdress)
            await state.update_data(client_id=client_id)
            await message.answer(
                "Новый номер адреса (последнее число): <code>18</code> → 10.0.0.18.\n"
                "Устройство подключится заново только с новыми файлами — пришлю их сразу.",
                reply_markup=get_vpn_cancel_kb(client_id),
            )
        elif action == "delete":
            client = await wg.get_client(client_id)
            await message.edit_reply_markup(reply_markup=get_vpn_delete_kb(client))
        elif action == "delete_yes":
            client = await wg.get_client(client_id)
            await wg.delete_client(client_id)
            await traffic.forget(client_id)
            notice = f"🗑️ {client.name} удалён — его файлы больше не подключатся"
            html, clients = await _list_html(wg)
            await show_rich(message, html, get_vpn_list_kb(clients))
        elif action == "files":
            await send_configs(message, wg, client_id)
    except VpnError as e:
        logger.warning("VPN action %s failed: %s", action, e)
        error = f"Сервер VPN не ответил: {e}"
    except Exception:
        # DB, 7z, Telegram: the button must still get its answer, and the owner a reason.
        logger.exception("VPN action %s failed", action)
        error = "Что-то пошло не так — подробности в логе бота"
    else:
        error = None

    if error and answered:
        await message.answer(error)
    elif error:
        await query.answer(error, show_alert=True)
    elif not answered:
        await query.answer(notice)


async def _set_expiry(wg: WgEasy, client_id: int, arg: str) -> str:
    client = await wg.get_client(client_id)
    now = datetime.now(UTC)
    expired = client.expires_at is not None and client.expires_at <= now
    # A client wg-easy switched off when its date passed comes back with the extension; one
    # the owner paused by hand stays paused.
    enabled = True if expired else client.enabled
    if arg == "none":
        await wg.update_client(client_id, expiresAt=None, enabled=enabled)
        return "♾️ Доступ бессрочный"
    start = client.expires_at if client.expires_at and not expired else now
    until = start + timedelta(days=int(arg))
    await wg.update_client(client_id, expiresAt=until.isoformat(), enabled=enabled)
    return f"⏳ Доступ до {until.astimezone():%d.%m.%Y}"


async def send_configs(message: Message, wg: WgEasy, client_id: int) -> None:
    client = await wg.get_client(client_id)
    full, lan = profiles(client.name, await wg.configuration(client_id))
    await message.answer_media_group(
        [
            InputMediaDocument(media=BufferedInputFile(full.config.encode(), filename=full.filename)),
            InputMediaDocument(
                media=BufferedInputFile(lan.config.encode(), filename=lan.filename),
                caption=files_caption(client, full.tunnel, lan.tunnel),
                parse_mode="HTML",
            ),
        ]
    )


async def send_exe(message: Message, wg: WgEasy, client_id: int) -> str | None:
    if missing := installer.missing_parts():
        return f"EXE здесь не собрать: нет {', '.join(missing)} (есть только в образе на сервере)"
    client = await wg.get_client(client_id)
    full, lan = profiles(client.name, await wg.configuration(client_id))
    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "upload_document")
    data = await asyncio.to_thread(installer.build_exe, full, lan)
    await message.answer_document(
        BufferedInputFile(data, filename=installer.exe_name(client.name)),
        caption=exe_caption(client),
    )
    return None


@router.message(VpnForm.new, _FORM_TEXT)
async def vpn_new(message: Message, state: FSMContext) -> None:
    name, wanted = parse_new(message.text or "")
    if not name or len(name) > NAME_MAX:
        await message.answer(f"Имя от 1 до {NAME_MAX} символов. Ещё раз:", reply_markup=get_vpn_cancel_kb())
        return
    wg = WgEasy()
    client_id: int | None = None
    try:
        clients = await wg.list_clients()
        number = addressing.pick(_taken(clients), wanted)
        client_id = await wg.create_client(name)
        await wg.update_client(client_id, ipv4Address=addressing.address(number))
        html, client = await _card_html(wg, client_id)
    except addressing.AddressError as e:
        await message.answer(f"Не выйдет: {e}. Ещё раз:", reply_markup=get_vpn_cancel_kb())
        return
    except VpnError as e:
        # wg-easy gives a new peer the lowest free address — one of the owner's .2–.9. A peer
        # left there by a failed readdress would be a live key nobody asked for.
        if client_id is not None:
            try:
                await wg.delete_client(client_id)
            except VpnError:
                logger.warning("Could not remove half-created VPN client %s", client_id)
        await state.clear()
        await message.answer(f"Сервер VPN не ответил: {e}")
        return
    await state.clear()
    logger.info("VPN client created: %s at %s", name, client.ipv4)
    await answer_rich(message, html, get_vpn_card_kb(client))


@router.message(VpnForm.rename, _FORM_TEXT)
async def vpn_rename(message: Message, state: FSMContext) -> None:
    client_id = int((await state.get_data())["client_id"])
    # One line: wg-easy refuses control characters, and a newline would come back as a 400.
    name = " ".join((message.text or "").split())
    if not name or len(name) > NAME_MAX:
        await message.answer(f"Имя от 1 до {NAME_MAX} символов. Ещё раз:", reply_markup=get_vpn_cancel_kb(client_id))
        return
    wg = WgEasy()
    try:
        await wg.update_client(client_id, name=name)
        html, client = await _card_html(wg, client_id)
    except VpnError as e:
        await state.clear()
        await message.answer(f"Сервер VPN не ответил: {e}")
        return
    await state.clear()
    await answer_rich(message, html, get_vpn_card_kb(client))


@router.message(VpnForm.readdress, _FORM_TEXT)
async def vpn_readdress(message: Message, state: FSMContext) -> None:
    client_id = int((await state.get_data())["client_id"])
    text = (message.text or "").strip().lstrip(".")
    wg = WgEasy()
    try:
        if not text.isdecimal():
            raise addressing.AddressError("нужно число, например 18")
        clients = await wg.list_clients()
        number = addressing.pick(_taken(clients, except_id=client_id), int(text))
        await wg.update_client(client_id, ipv4Address=addressing.address(number))
        html, client = await _card_html(wg, client_id)
    except addressing.AddressError as e:
        await message.answer(f"Не выйдет: {e}. Ещё раз:", reply_markup=get_vpn_cancel_kb(client_id))
        return
    except VpnError as e:
        await state.clear()
        await message.answer(f"Сервер VPN не ответил: {e}")
        return
    await state.clear()
    await answer_rich(message, html, get_vpn_card_kb(client))
    # The address lives in the configuration: the old files no longer match the server.
    await send_configs(message, wg, client_id)
