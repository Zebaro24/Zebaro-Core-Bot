import asyncio
import logging
import os

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.core.service_manager import ServiceManager
from src.interfaces.tg.middlewares.admin import AdminMiddleware

logger = logging.getLogger("tg.handlers.admin.services")

router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())


# ── Callback data ────────────────────────────────────────────────────────────


class InfraToggle(CallbackData, prefix="infra"):
    name: str
    infra_mid: int
    svc_mid: int


class SvcToggle(CallbackData, prefix="svc"):
    name: str
    infra_mid: int
    svc_mid: int


class ServicesRefresh(CallbackData, prefix="sref"):
    infra_mid: int
    svc_mid: int


class BotRestart(CallbackData, prefix="brestart"):
    pass


# ── Builders ─────────────────────────────────────────────────────────────────


def _infra_status(enabled: bool, healthy: bool) -> tuple[str, str]:
    if not enabled:
        return "🔴", "выключена"
    return ("🟢", "пашет 🔥") if healthy else ("🟡", "включена, но не отвечает")


async def _infra_message(sm: ServiceManager, infra_mid: int, svc_mid: int) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🛠 <b>Инфраструктура</b>\n"]

    for name, infra in sm.all_infrastructure.items():
        enabled = sm.is_infra_enabled(name)
        health = await sm.check_infra_health(name)
        emoji, status = _infra_status(enabled, health)
        linked = sm.get_services_for_infra(name)
        linked_str = ", ".join(linked) if linked else "—"
        lines.append(f"{emoji} <b>{infra.display_name}</b> — {status}")
        lines.append(f"   └ сервисы: {linked_str}\n")

    builder = InlineKeyboardBuilder()
    for name, infra in sm.all_infrastructure.items():
        if sm.is_infra_enabled(name):
            builder.button(
                text=f"Вырубить {infra.display_name}",
                callback_data=InfraToggle(name=name, infra_mid=infra_mid, svc_mid=svc_mid),
                style="danger",
            )
        else:
            builder.button(
                text=f"Врубить {infra.display_name}",
                callback_data=InfraToggle(name=name, infra_mid=infra_mid, svc_mid=svc_mid),
                style="success",
            )
    builder.adjust(1)
    return "\n".join(lines), builder.as_markup()


async def _svc_message(sm: ServiceManager, infra_mid: int, svc_mid: int) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["⚡️ <b>Сервисы</b>\n"]

    for name, svc in sm.all_services.items():
        enabled = sm.is_service_enabled(name)
        emoji = "🟢" if enabled else "🔴"
        status = "в деле" if enabled else "отдыхает"
        deps_str = ", ".join(svc.infra_deps) if svc.infra_deps else "—"
        restart_note = " <i>⚠️ нужен рестарт</i>" if svc.needs_restart else ""
        lines.append(f"{emoji} <b>{svc.display_name}</b> — {status}{restart_note}")
        if svc.infra_deps:
            lines.append(f"   └ инфра: {deps_str}\n")
        else:
            lines.append("")

    builder = InlineKeyboardBuilder()
    for name, svc in sm.all_services.items():
        if sm.is_service_enabled(name):
            builder.button(
                text=f"Вырубить {svc.display_name}",
                callback_data=SvcToggle(name=name, infra_mid=infra_mid, svc_mid=svc_mid),
                style="danger",
            )
        else:
            builder.button(
                text=f"Врубить {svc.display_name}",
                callback_data=SvcToggle(name=name, infra_mid=infra_mid, svc_mid=svc_mid),
                style="success",
            )
    builder.button(
        text="🔄 Обновить",
        callback_data=ServicesRefresh(infra_mid=infra_mid, svc_mid=svc_mid),
        style="primary",
    )
    builder.button(
        text="⚡ Перезапустить бота",
        callback_data=BotRestart(),
        style="danger",
    )
    builder.adjust(1)
    return "\n".join(lines), builder.as_markup()


async def _update_both(bot: Bot, sm: ServiceManager, infra_mid: int, svc_mid: int, chat_id: int) -> None:
    infra_text, infra_kb = await _infra_message(sm, infra_mid, svc_mid)
    svc_text, svc_kb = await _svc_message(sm, infra_mid, svc_mid)
    for mid, text, kb in [(infra_mid, infra_text, infra_kb), (svc_mid, svc_text, svc_kb)]:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=mid, reply_markup=kb)
        except TelegramBadRequest:
            pass


# ── Handlers ─────────────────────────────────────────────────────────────────


@router.message(Command("services"))
async def services_command(message: Message) -> None:
    sm = ServiceManager.get_instance()

    infra_msg = await message.answer("⏳")
    svc_msg = await message.answer("⏳")
    infra_mid, svc_mid = infra_msg.message_id, svc_msg.message_id

    infra_text, infra_kb = await _infra_message(sm, infra_mid, svc_mid)
    svc_text, svc_kb = await _svc_message(sm, infra_mid, svc_mid)

    await infra_msg.edit_text(infra_text, reply_markup=infra_kb)
    await svc_msg.edit_text(svc_text, reply_markup=svc_kb)


@router.callback_query(InfraToggle.filter())
async def infra_toggle_callback(callback: CallbackQuery, callback_data: InfraToggle) -> None:
    sm = ServiceManager.get_instance()
    try:
        if sm.is_infra_enabled(callback_data.name):
            await sm.disable_infrastructure(callback_data.name)
        else:
            await sm.enable_infrastructure(callback_data.name)
    except Exception as e:
        logger.exception("Failed to toggle infra %s", callback_data.name)
        await callback.answer(f"💀 Ошибка: {e}", show_alert=True)
        return

    if callback.message and callback.bot:
        await _update_both(callback.bot, sm, callback_data.infra_mid, callback_data.svc_mid, callback.message.chat.id)
    await callback.answer()


@router.callback_query(SvcToggle.filter())
async def svc_toggle_callback(callback: CallbackQuery, callback_data: SvcToggle) -> None:
    sm = ServiceManager.get_instance()
    try:
        if sm.is_service_enabled(callback_data.name):
            await sm.disable_service(callback_data.name)
        else:
            await sm.enable_service(callback_data.name)
    except Exception as e:
        logger.exception("Failed to toggle service %s", callback_data.name)
        await callback.answer(f"💀 Ошибка: {e}", show_alert=True)
        return

    if callback.message and callback.bot:
        await _update_both(callback.bot, sm, callback_data.infra_mid, callback_data.svc_mid, callback.message.chat.id)
    await callback.answer()


@router.callback_query(ServicesRefresh.filter())
async def services_refresh_callback(callback: CallbackQuery, callback_data: ServicesRefresh) -> None:
    sm = ServiceManager.get_instance()
    if callback.message and callback.bot:
        await _update_both(callback.bot, sm, callback_data.infra_mid, callback_data.svc_mid, callback.message.chat.id)
    await callback.answer("🔄 Свежак!")


@router.callback_query(BotRestart.filter())
async def bot_restart_callback(callback: CallbackQuery) -> None:
    await callback.answer("⚡ Перезапускаю... держись!", show_alert=True)
    asyncio.create_task(_do_restart())


async def _do_restart() -> None:
    await asyncio.sleep(0.5)
    logger.info("Bot restart triggered by admin via Telegram")
    os._exit(0)
