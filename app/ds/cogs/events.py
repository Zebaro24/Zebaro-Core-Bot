import logging

from discord.ext import commands

logger = logging.getLogger("discord.events")


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Бот {self.bot.user} подключился!")

        try:
            synced = await self.bot.tree.sync()
            logger.info(f"Синхронизировано {len(synced)} команд.")
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")


async def setup(bot):
    await bot.add_cog(Events(bot))
