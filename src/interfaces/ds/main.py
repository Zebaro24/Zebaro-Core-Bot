import asyncio
import logging

import discord
from discord.ext import commands

from src.config import settings
from src.interfaces.ds.cogs.commands import Commands
from src.interfaces.ds.cogs.events import Events

logger = logging.getLogger("ds.main")


async def start_bot() -> None:
    intents = discord.Intents.default()
    activity = discord.Activity(type=discord.ActivityType.playing, name="Кодинг класних фич 😎")

    bot = commands.Bot(
        command_prefix=None,  # type: ignore
        intents=intents,
        activity=activity,
        status=discord.Status.dnd,
    )

    await bot.add_cog(Events(bot))
    await bot.add_cog(Commands(bot))

    try:
        logger.info("Starting Discord bot")
        await bot.start(settings.discord_bot_token)
    except asyncio.CancelledError:
        logger.info("Discord bot shutting down...")
        await bot.close()
    except Exception as e:
        logger.exception("Discord bot crashed: %s", e)
