import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())

from src.interfaces.tg import commands


@pytest.fixture
def ids(mocker):
    settings = MagicMock(telegram_admin_id=1, telegram_docker_access_ids=[1, 2])
    mocker.patch.object(commands, "settings", settings)


def test_three_menus_everyone_server_and_admin(ids):
    menus = {chat_id: [command.command for command in menu] for menu, chat_id in commands.menus()}

    assert menus[None] == ["start", "get_chat_id"]
    assert "server_status" in menus[2] and "job_stats" not in menus[2]
    assert {"server_status", "job_stats", "vpn"} <= set(menus[1])


@pytest.mark.asyncio
async def test_one_refused_menu_does_not_cost_the_others(ids):
    bot = MagicMock()
    bot.set_my_commands = AsyncMock(side_effect=[None, Exception("chat not found"), None])

    await commands.set_commands(bot)

    assert bot.set_my_commands.await_count == 3
