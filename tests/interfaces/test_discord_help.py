import sys
from unittest.mock import AsyncMock, MagicMock

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())

import pytest

from src.interfaces.ds.commands.help import TELEGRAM, help_command, help_text


def test_help_lists_the_slash_commands_and_points_to_telegram():
    text = help_text([help_command])
    assert "`/help` — Что умеет бот" in text
    assert TELEGRAM in text


@pytest.mark.asyncio
async def test_help_answers_only_the_one_who_asked():
    interaction = MagicMock()
    interaction.client.tree.get_commands.return_value = [help_command]
    interaction.response.send_message = AsyncMock()

    await help_command.callback(interaction)  # type: ignore[call-arg]

    args, kwargs = interaction.response.send_message.await_args
    assert kwargs["ephemeral"] is True and "`/help`" in args[0]
