import logging
from typing import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from src.config import settings

logger = logging.getLogger("tg.middleware.admin")


class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable],
        event: TelegramObject,
        data: dict,
    ):
        user: User | None = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user is not None and user.id != settings.telegram_admin_id:
            logger.warning("Unauthorized admin access from user_id=%s", user.id)
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Ты не админ", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ Ты не админ")
            return None

        return await handler(event, data)
