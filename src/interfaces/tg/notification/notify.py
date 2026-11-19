"""Claude's notifications in the owner's chat: one live message per project, gone once seen.

"Seen" is what the owner's side can observe: the next prompt in Claude (DELETE /notify?session=…),
the ✓ button, or the 12-hour sweep. A Telegram message that is already gone is not an error.
"""

import asyncio
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from src.config import settings
from src.interfaces.tg.formatters.notify import notice_to_html
from src.interfaces.tg.keyboards.notify import NotifyCallback, get_notify_kb
from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.services import notify as store
from src.services.notify import Notice

logger = logging.getLogger("tg.notification.notify")

router = Router()
router.callback_query.middleware(AdminMiddleware())

_locks: dict[str, asyncio.Lock] = {}


async def _delete(bot: Bot, message_ids: list[int]) -> None:
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=settings.telegram_admin_id, message_id=message_id)
        except TelegramAPIError as e:
            logger.info("Notify message %s not deleted: %s", message_id, e)


async def deliver(bot: Bot, notice: Notice) -> None:
    """Send first, then drop the project's previous message: a failed send leaves the old one.

    Only the send can fail this call (the caller answers 503); what follows is best effort, so a
    message already in the chat never comes back as an error the hook might retry. One project at a
    time: two pings at once would each miss the other's record and both stay.
    """
    async with _locks.setdefault(notice.project, asyncio.Lock()):
        sent = await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=notice_to_html(notice),
            reply_markup=get_notify_kb(),
            disable_web_page_preview=True,
        )
        try:
            previous = await store.take_project(notice.project)
            await store.remember(notice, sent.message_id)
            await _delete(bot, previous)
        except Exception:
            logger.exception("Notification for %s sent, its predecessor not cleared", notice.project)


async def clear_session(bot: Bot, session: str) -> int:
    message_ids = await store.take_session(session)
    await _delete(bot, message_ids)
    return len(message_ids)


async def notify_sweep(bot: Bot) -> None:
    await _delete(bot, await store.take_expired())


@router.callback_query(NotifyCallback.filter())
async def seen_callback(query: CallbackQuery) -> None:
    """✓ — needs no record: it deletes the message it sits on."""
    if isinstance(query.message, Message):
        await store.take_message(query.message.message_id)
        try:
            await query.message.delete()
        except TelegramAPIError as e:
            logger.info("Notify message not deleted on ✓: %s", e)
    await query.answer()
