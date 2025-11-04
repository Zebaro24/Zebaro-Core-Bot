from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.docker_service.manager import DockerManager
from app.tg.keyboards.docker import get_docker_manager_kb
from app.tg.middlewares.docker_middleware import docker_middleware

router = Router()
router.message.middleware(docker_middleware)


@router.message(Command("server_status"))
async def server_status_command(message: Message, docker_manager: DockerManager):
    await message.answer("👀 Подключаюсь к проектам… Держись, щас всё проверим! ⚡")

    if bot := message.bot:
        await bot.send_chat_action(message.chat.id, "typing")

    docker_manager.update_projects()

    await message.answer(docker_manager.get_projects_info(), reply_markup=get_docker_manager_kb(docker_manager))
