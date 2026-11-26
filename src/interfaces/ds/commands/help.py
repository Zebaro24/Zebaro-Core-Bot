from typing import Any

import discord
from discord import app_commands

TELEGRAM = "https://t.me/zebaro_core_bot"


def help_text(commands: list[Any]) -> str:
    """The bot's own slash commands, read from its tree, so a new command shows up here by itself."""
    lines = ["**Zebaro Core Bot** — помощник Zebaro. В Discord пока немного:"]
    lines += [
        f"• `/{c.name}` — {c.description}"
        for c in sorted(commands, key=lambda c: c.name)
        if isinstance(c, app_commands.Command | app_commands.Group)
    ]
    lines.append(f"Основное (сервер, поиск работы, GitHub, VPN) — в Telegram: {TELEGRAM}")
    return "\n".join(lines)


@app_commands.command(name="help", description="Что умеет бот")
async def help_command(interaction: discord.Interaction) -> None:
    tree = getattr(interaction.client, "tree", None)
    commands = list(tree.get_commands()) if tree is not None else [help_command]
    await interaction.response.send_message(help_text(commands), ephemeral=True)
