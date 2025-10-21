from aiogram import BaseMiddleware
from aiogram.types import Message

from app.config import settings


class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        if event.from_user.id != settings.telegram_admin_id:
            await event.answer("⛔ Ты не админ")
            return None
        return await handler(event, data)
