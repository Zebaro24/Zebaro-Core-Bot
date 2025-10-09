from io import BytesIO

from aiogram import Router
from aiogram.types import CallbackQuery, InputFile, BufferedInputFile

from app.services.docker_service.manager import DockerManager
from app.tg.keyboards.docker import DockerProjectCallback, get_docker_manager_kb, get_docker_project_kb, \
    DockerContainerCallback, DockerManagerCallback, get_docker_container_kb
from app.tg.middlewares.admin_middleware import AdminMiddleware
from app.tg.middlewares.docker_middleware import docker_middleware

router = Router()
router.callback_query.middleware(docker_middleware)


@router.callback_query(DockerManagerCallback.filter())
async def manager_info_callback(query: CallbackQuery, callback_data: DockerManagerCallback,
                                docker_manager: DockerManager):
    if callback_data.action == "refresh":
        await query.message.edit_text("⏳ Загрузка...", reply_markup=None)
        docker_manager.update_projects()
        await query.message.edit_text(docker_manager.get_projects_info(),
                                      reply_markup=get_docker_manager_kb(docker_manager))


@router.callback_query(DockerProjectCallback.filter())
async def project_info_callback(query: CallbackQuery, callback_data: DockerProjectCallback,
                                docker_manager: DockerManager):
    if not docker_manager.project_dict:
        await query.answer("⏳ Загрузка...")
        docker_manager.update_projects()

    project = docker_manager.get_project_by_key(callback_data.project_key)
    if not project:
        await query.answer("Проект не найден")
        return

    await query.message.edit_text("⏳ Загрузка...", reply_markup=None)
    if callback_data.action in ["get", "refresh"]:
        project.reload_containers()
        project.update_stats()
        await query.message.edit_text(project.get_info(), reply_markup=get_docker_project_kb(project))

    await query.answer()


@router.callback_query(DockerContainerCallback.filter())
async def container_info_callback(query: CallbackQuery, callback_data: DockerContainerCallback,
                                  docker_manager: DockerManager):
    if not docker_manager.project_dict:
        await query.answer("⏳ Загрузка...")
        docker_manager.update_projects()

    container = docker_manager.get_container_by_key(callback_data.container_key)
    if not container:
        await query.answer("Контейнер не найден")
        return

    if callback_data.action in ["get", "refresh"]:
        await query.message.edit_text("⏳ Загрузка...", reply_markup=None)
        container.reload()
        container.update_stats()
        await query.message.edit_text(container.get_info(), reply_markup=get_docker_container_kb(container))
    elif callback_data.action == "start_stop":
        if container.get_status() != "Exited":
            await query.answer("Контейнер останавливается...")
            container.stop()
        else:
            await query.answer("Контейнер запускается...")
            container.start()
        return
    elif callback_data.action == "restart":
        container.restart()
    elif callback_data.action == "log_file":
        logs = container.get_short_log()

        file = BufferedInputFile(logs.encode("utf-8"), filename=f"{container.get_name()}_logs.txt")

        await query.message.reply_document(file)

    await query.answer()
