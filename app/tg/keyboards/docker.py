from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.docker_service.container import DockerContainer
from app.services.docker_service.manager import DockerManager
from app.services.docker_service.project import DockerProject


class DockerManagerCallback(CallbackData, prefix="docker_manager"):
    action: str


class DockerProjectCallback(CallbackData, prefix="docker_project"):
    action: str
    project_key: str | None


class DockerContainerCallback(CallbackData, prefix="docker_container"):
    action: str
    container_key: str | None


def get_docker_manager_kb(manager: DockerManager):
    keyboard_list = []
    for project_key, project in manager.project_dict.items():
        keyboard_list.append(
            [
                InlineKeyboardButton(
                    text=project.name, callback_data=DockerProjectCallback(action="get", project_key=project_key).pack()
                )
            ]
        )

    keyboard_list.append(
        [InlineKeyboardButton(text="Обновить 🔄", callback_data=DockerManagerCallback(action="refresh").pack())]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard_list)


def get_docker_project_kb(project: DockerProject):
    keyboard_list = []
    for container in project.containers:
        keyboard_list.append(
            [
                InlineKeyboardButton(
                    text=container.get_name().title(),
                    callback_data=DockerContainerCallback(action="get", container_key=container.get_name()).pack(),
                )
            ]
        )

    keyboard_list.append(
        [
            InlineKeyboardButton(
                text="Обновить 🔄",
                callback_data=DockerProjectCallback(action="refresh", project_key=project.name).pack(),
            ),
            InlineKeyboardButton(text="Вернуться 🔙", callback_data=DockerManagerCallback(action="refresh").pack()),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard_list)


def get_docker_container_kb(container: DockerContainer):
    keyboard_list = [
        [
            InlineKeyboardButton(
                text="Старт ▶️ / Стоп ⏹️",
                callback_data=DockerContainerCallback(action="start_stop", container_key=container.get_name()).pack(),
            ),
            InlineKeyboardButton(
                text="Рестарт 🔁",
                callback_data=DockerContainerCallback(action="restart", container_key=container.get_name()).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="Получить лог файл 📄",
                callback_data=DockerContainerCallback(action="log_file", container_key=container.get_name()).pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="Обновить 🔄",
                callback_data=DockerContainerCallback(action="refresh", container_key=container.get_name()).pack(),
            ),
            InlineKeyboardButton(text="Вернуться 🔙", callback_data=DockerManagerCallback(action="refresh").pack()),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard_list)
