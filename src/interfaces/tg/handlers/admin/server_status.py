import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.interfaces.tg.formatters.docker import format_manager_info
from src.interfaces.tg.keyboards.docker import get_docker_manager_kb
from src.interfaces.tg.middlewares.docker import docker_middleware
from src.services.docker.manager import DockerManager

logger = logging.getLogger("tg.handlers.admin.server_status")

router = Router()
router.message.middleware(docker_middleware)


@router.message(Command("server_status"))
async def server_status_command(message: Message, docker_manager: DockerManager) -> None:
    logger.info("Server status requested by user_id=%s", message.from_user.id if message.from_user else "unknown")
    await message.answer("👀 Подключаюсь к проектам… Держись, щас всё проверим! ⚡")

    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")

    docker_manager.update_projects()
    docker_manager.update_stats()

    await message.answer(
        format_manager_info(docker_manager),
        reply_markup=get_docker_manager_kb(docker_manager),
    )
