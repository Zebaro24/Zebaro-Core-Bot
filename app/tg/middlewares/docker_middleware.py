from typing import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from app.config import settings
from app.services.docker_service.manager import DockerManager


class DockerMiddleware(BaseMiddleware):
    def __init__(self):
        self.docker = DockerManager()

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

        access_ids = settings.telegram_docker_access_ids or []

        if user is None or user.id not in access_ids:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ У тебя нет доступа к контейнерам", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ У тебя нет доступа к контейнерам")
            return None

        data["docker_manager"] = self.docker
        return await handler(event, data)


docker_middleware = DockerMiddleware()
