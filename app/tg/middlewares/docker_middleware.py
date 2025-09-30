from aiogram import BaseMiddleware
from app.services.docker_service.manager import DockerManager
from aiogram.types import Message
from app.config import settings


class DockerMiddleware(BaseMiddleware):
    def __init__(self):
        self.docker = DockerManager()

    async def __call__(self, handler, event: Message, data: dict):
        if event.from_user.id not in settings.telegram_docker_access_ids:
            await event.answer("⛔ У тебя нет доступа к контейнерам")
            return None
        data["docker_manager"] = self.docker
        return await handler(event, data)

docker_middleware = DockerMiddleware()
