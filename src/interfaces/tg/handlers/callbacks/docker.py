import logging

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from src.interfaces.tg.formatters.docker import format_manager_info
from src.interfaces.tg.keyboards.docker import (
    DockerContainerCallback,
    DockerManagerCallback,
    DockerProjectCallback,
    get_docker_container_kb,
    get_docker_manager_kb,
    get_docker_project_kb,
)
from src.interfaces.tg.middlewares.docker import docker_middleware
from src.services.docker.manager import DockerManager

logger = logging.getLogger("tg.handlers.callbacks.docker")

router = Router()
router.callback_query.middleware(docker_middleware)


@router.callback_query(DockerManagerCallback.filter())
async def manager_info_callback(
    query: CallbackQuery,
    callback_data: DockerManagerCallback,
    docker_manager: DockerManager,
) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return

    if callback_data.action == "refresh":
        await query.message.edit_text("⏳ Загрузка...", reply_markup=None)
        docker_manager.update_projects()
        docker_manager.update_stats()
        await query.message.edit_text(
            format_manager_info(docker_manager),
            reply_markup=get_docker_manager_kb(docker_manager),
        )
        logger.info("Docker manager refreshed by user_id=%s", query.from_user.id)

    await query.answer()


@router.callback_query(DockerProjectCallback.filter())
async def project_info_callback(
    query: CallbackQuery,
    callback_data: DockerProjectCallback,
    docker_manager: DockerManager,
) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return

    if not docker_manager.project_dict:
        await query.answer("⏳ Загрузка...")
        docker_manager.update_projects()

    if not callback_data.project_key:
        await query.answer("Ключ проекта не указан")
        return

    project = docker_manager.get_project_by_key(callback_data.project_key)
    if not project:
        await query.answer("Проект не найден")
        logger.warning("Project not found: key=%s", callback_data.project_key)
        return

    if callback_data.action in ("get", "refresh"):
        await query.message.edit_text("⏳ Загрузка...", reply_markup=None)
        project.reload_containers()
        project.update_stats()
        await query.message.edit_text(project.get_info(), reply_markup=get_docker_project_kb(project))
        logger.info("Project info shown: %s", project.name)

    await query.answer()


@router.callback_query(DockerContainerCallback.filter())
async def container_info_callback(
    query: CallbackQuery,
    callback_data: DockerContainerCallback,
    docker_manager: DockerManager,
) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return

    if not docker_manager.project_dict:
        await query.answer("⏳ Загрузка...")
        docker_manager.update_projects()

    if not callback_data.container_key:
        await query.answer("Ключ контейнера не указан")
        return

    container = docker_manager.get_container_by_key(callback_data.container_key)
    if not container:
        await query.answer("Контейнер не найден")
        logger.warning("Container not found: key=%s", callback_data.container_key)
        return

    action = callback_data.action

    if action in ("get", "refresh"):
        await query.message.edit_text("⏳ Загрузка...", reply_markup=None)
        container.reload()
        container.update_stats()
        await query.message.edit_text(container.get_info(), reply_markup=get_docker_container_kb(container))
        logger.info("Container info shown: %s", container.get_name())

    elif action == "start_stop":
        if container.get_status() != "Exited":
            await query.answer("Контейнер останавливается...")
            container.stop()
        else:
            await query.answer("Контейнер запускается...")
            container.start()
        return

    elif action == "restart":
        container.restart()

    elif action == "log_file":
        file = BufferedInputFile(
            container.get_short_log().encode("utf-8"),
            filename=f"{container.get_name()}_logs.txt",
        )
        await query.message.reply_document(file)
        logger.info("Log file sent for container: %s", container.get_name())

    await query.answer()
