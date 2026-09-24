from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.interfaces.tg.keyboards.grid import button_grid
from src.services.docker.container import DockerContainer
from src.services.docker.manager import DockerManager
from src.services.docker.project import DockerProject


class DockerManagerCallback(CallbackData, prefix="docker_manager"):
    action: str
    page: int = 0


class DockerProjectCallback(CallbackData, prefix="docker_project"):
    action: str
    project_key: str | None
    page: int = 0


class DockerContainerCallback(CallbackData, prefix="docker_container"):
    action: str
    container_key: str | None


def get_docker_manager_kb(manager: DockerManager, page: int = 0) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{project.get_status_emoji()} {project.name}",
            callback_data=DockerProjectCallback(action="get", project_key=key).pack(),
        )
        for key, project in manager.sorted_projects()
    ]
    rows = button_grid(buttons, page, lambda p: DockerManagerCallback(action="refresh", page=p).pack())
    rows.append(
        [InlineKeyboardButton(text="Обновить 🔄", callback_data=DockerManagerCallback(action="refresh").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_docker_project_kb(project: DockerProject, page: int = 0) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{container.get_status_emoji()} {container.get_name()}",
            callback_data=DockerContainerCallback(action="get", container_key=container.get_name()).pack(),
        )
        for container in project.sorted_containers()
    ]
    rows = button_grid(
        buttons, page, lambda p: DockerProjectCallback(action="refresh", project_key=project.name, page=p).pack()
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Обновить 🔄",
                callback_data=DockerProjectCallback(action="refresh", project_key=project.name).pack(),
            ),
            InlineKeyboardButton(
                text="Вернуться 🔙",
                callback_data=DockerManagerCallback(action="refresh").pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_docker_container_kb(container: DockerContainer) -> InlineKeyboardMarkup:
    name = container.get_name()
    toggle = ("Стоп ⏹️", "start_stop") if container.is_running() else ("Старт ▶️", "start_stop")
    rows = [
        [
            InlineKeyboardButton(
                text=toggle[0], callback_data=DockerContainerCallback(action=toggle[1], container_key=name).pack()
            ),
            InlineKeyboardButton(
                text="Рестарт 🔁",
                callback_data=DockerContainerCallback(action="restart", container_key=name).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="Лог файлом 📄",
                callback_data=DockerContainerCallback(action="log_file", container_key=name).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="Обновить 🔄",
                callback_data=DockerContainerCallback(action="refresh", container_key=name).pack(),
            ),
            InlineKeyboardButton(
                text="Вернуться 🔙",
                # Back to its own project, not to the whole server.
                callback_data=DockerProjectCallback(action="get", project_key=container.get_project_name()).pack(),
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
