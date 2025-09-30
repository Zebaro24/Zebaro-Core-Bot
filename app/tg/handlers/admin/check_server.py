from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from app.services.docker_service.manager import DockerManager
from app.tg.keyboards.docker import get_docker_manager_kb
from app.tg.middlewares.admin_middleware import AdminMiddleware
from app.tg.middlewares.docker_middleware import docker_middleware

router = Router()
router.message.middleware(AdminMiddleware())
router.message.middleware(docker_middleware)


@router.message(Command("check_server"))
async def check_server_command(message: Message, docker_manager: DockerManager):
    await message.answer("Check server...")

    await message.bot.send_chat_action(message.chat.id, "typing")

    docker_manager.update_projects()

    await message.answer(docker_manager.get_projects_info(), reply_markup=get_docker_manager_kb(docker_manager))