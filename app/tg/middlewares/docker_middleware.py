from aiogram import BaseMiddleware
from app.services.docker_service.manager import DockerManager
from aiogram.types import Message


class DockerMiddleware(BaseMiddleware):
    def __init__(self):
        self.docker = DockerManager()

    async def __call__(self, handler, event: Message, data: dict):
        data["docker_manager"] = self.docker
        return await handler(event, data)

docker_middleware = DockerMiddleware()
