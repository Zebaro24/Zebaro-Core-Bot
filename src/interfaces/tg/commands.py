"""The command menu next to the message field, set at every start.

Without it the commands lived only in the /start greeting, and the owner pressed /start each
time to see them (06.10.2026). Three menus, as in the greeting: everyone, the people with
access to the server's containers, and the admin.
"""

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from src.config import settings

logger = logging.getLogger("tg.commands")

EVERYONE = [
    BotCommand(command="start", description="Приветствие и список команд"),
    BotCommand(command="get_chat_id", description="Chat ID и Thread ID"),
]
SERVER = [
    BotCommand(command="server_status", description="Контейнеры на сервере"),
    BotCommand(command="server_speed", description="Скорость интернета на сервере"),
]
ADMIN = [
    BotCommand(command="get_job_openings", description="Поиск новых вакансий"),
    BotCommand(command="job_stats", description="Статистика поиска: /job_stats 30"),
    BotCommand(command="vpn", description="Люди в VPN: онлайн, трафик, файлы"),
    BotCommand(command="services", description="Сервисы и инфраструктура"),
    BotCommand(command="mongo", description="База MongoDB"),
]


def menus() -> list[tuple[list[BotCommand], int | None]]:
    """Each menu and the chat it is for; None — the default for everyone."""
    result: list[tuple[list[BotCommand], int | None]] = [(EVERYONE, None)]
    admin_id = int(settings.telegram_admin_id)
    server_ids = [int(chat_id) for chat_id in settings.telegram_docker_access_ids if int(chat_id) != admin_id]
    result += [(EVERYONE + SERVER, chat_id) for chat_id in server_ids]
    result.append((EVERYONE + SERVER + ADMIN, admin_id))
    return result


async def set_commands(bot: Bot) -> None:
    for commands, chat_id in menus():
        scope = BotCommandScopeDefault() if chat_id is None else BotCommandScopeChat(chat_id=chat_id)
        try:
            await bot.set_my_commands(commands, scope=scope)
        except Exception as e:
            # A chat that never opened the bot refuses its menu; the rest still get theirs.
            logger.warning("Could not set the command menu for %s: %s", chat_id or "everyone", e)
