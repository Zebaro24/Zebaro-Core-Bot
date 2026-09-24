import logging

from aiogram import Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from src.interfaces.tg.formatters.docker import (
    LOG_TAIL,
    format_container_rich,
    format_manager_rich,
    format_project_rich,
)
from src.interfaces.tg.keyboards.docker import (
    DockerContainerCallback,
    DockerManagerCallback,
    DockerProjectCallback,
    get_docker_container_kb,
    get_docker_manager_kb,
    get_docker_project_kb,
)
from src.interfaces.tg.middlewares.docker import docker_middleware
from src.interfaces.tg.rich import show_rich
from src.services.docker.manager import DockerManager

logger = logging.getLogger("tg.handlers.callbacks.docker")

LOG_FILE_TAIL = 5000

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
        docker_manager.update_projects()
        docker_manager.update_stats()
        await show_rich(
            query.message,
            format_manager_rich(docker_manager),
            get_docker_manager_kb(docker_manager, callback_data.page),
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
        project.reload_containers()
        project.update_stats()
        await show_rich(query.message, format_project_rich(project), get_docker_project_kb(project, callback_data.page))
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
    notice = None

    if action == "start_stop":
        if container.is_running():
            container.stop()
            notice = "⏹️ Остановлен"
        else:
            container.start()
            notice = "▶️ Запущен"
    elif action == "restart":
        container.restart()
        notice = "🔁 Перезапущен"
    elif action == "log_file":
        file = BufferedInputFile(
            container.get_log(tail=LOG_FILE_TAIL).encode("utf-8"),
            filename=f"{container.get_name()}_logs.txt",
        )
        await query.message.reply_document(file)
        logger.info("Log file sent for container: %s", container.get_name())
        await query.answer()
        return

    # Every other action ends on the refreshed card: the owner sees the new state at once.
    container.reload()
    container.update_stats()
    await show_rich(
        query.message,
        format_container_rich(container, container.get_log(tail=LOG_TAIL)),
        get_docker_container_kb(container),
    )
    logger.info("Container %s: %s", container.get_name(), action)
    await query.answer(notice)
