from typing import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

from app.config import settings


class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable], event: TelegramObject, data: dict):
        if isinstance(event, Message):
            user: User | None = event.from_user
            if user is None or user.id != settings.telegram_admin_id:
                await event.answer("⛔ Ты не админ")
                return None

        return await handler(event, data)
