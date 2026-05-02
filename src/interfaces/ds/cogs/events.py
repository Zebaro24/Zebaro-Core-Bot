import logging

from discord.ext import commands

logger = logging.getLogger("ds.events")


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        logger.info("Discord bot connected as %s", self.bot.user)
        try:
            synced = await self.bot.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception as e:
            logger.error("Failed to sync commands: %s", e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Events(bot))
