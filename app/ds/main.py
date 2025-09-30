import asyncio

from app.config import settings

import discord
from discord.ext import commands

from app.ds.cogs.commands import Commands
from app.ds.cogs.events import Events


async def start_bot():
    intents = discord.Intents.default()

    activity = discord.Activity(type=discord.ActivityType.playing, name="Кодинг класных фич 😎")
    status = discord.Status.dnd

    bot = commands.Bot(command_prefix=None, intents=intents, activity=activity, status=status) # type: ignore

    await bot.add_cog(Events(bot))
    await bot.add_cog(Commands(bot))

    await bot.start(settings.discord_bot_token)

if __name__ == "__main__":
    asyncio.run(start_bot())
