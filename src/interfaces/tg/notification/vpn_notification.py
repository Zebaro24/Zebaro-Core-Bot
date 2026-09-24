import logging
from html import escape

from aiogram import Bot
from aiogram.types import InputRichMessage

from src.config import settings
from src.interfaces.tg.formatters.vpn import format_weekly_vpn
from src.interfaces.tg.keyboards.vpn import get_vpn_expiring_kb
from src.services.vpn import traffic
from src.services.vpn.client import VpnError, WgEasy

logger = logging.getLogger("tg.notification.vpn")

# wg-easy's firewall hooks are checked once per bot start (WgEasy.apply_hooks is idempotent):
# without them the full profile has no internet and the panel is open to peers.
_hooks_applied = False


async def _apply_hooks(wg: WgEasy) -> None:
    global _hooks_applied
    if _hooks_applied:
        return
    await wg.apply_hooks()
    _hooks_applied = True


async def vpn_watch(bot: Bot) -> None:
    """Every few minutes: fold traffic into the history, tell the owner what is new."""
    wg = WgEasy()
    try:
        await _apply_hooks(wg)
        clients = await wg.list_clients()
        events = await traffic.snapshot(clients)
    except VpnError as e:
        logger.warning("VPN watch skipped: %s", e)
        return
    except Exception:
        logger.exception("VPN watch failed")
        return

    for client in events.first_connected:
        where = f" из {escape(client.endpoint.rpartition(':')[0])}" if client.endpoint else ""
        await bot.send_message(
            settings.telegram_admin_id,
            f"🟢 <b>{escape(client.name)}</b> ({client.ipv4}) впервые подключился к VPN{where}.",
            disable_notification=True,
        )
    for client in events.expiring:
        until = f"{client.expires_at.astimezone():%d.%m %H:%M}" if client.expires_at else ""
        await bot.send_message(
            settings.telegram_admin_id,
            f"⏳ У <b>{escape(client.name)}</b> доступ к VPN заканчивается {until}.",
            reply_markup=get_vpn_expiring_kb(client),
        )


async def vpn_weekly(bot: Bot) -> None:
    try:
        clients = await WgEasy().list_clients()
        week = await traffic.period([c.id for c in clients], days=7)
    except VpnError as e:
        logger.warning("VPN weekly skipped: %s", e)
        return
    except Exception:
        logger.exception("VPN weekly failed")
        return
    await bot.send_rich_message(
        chat_id=settings.telegram_admin_id,
        rich_message=InputRichMessage(html=format_weekly_vpn(clients, week)),
        disable_notification=True,
    )
