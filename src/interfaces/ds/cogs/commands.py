from discord.ext import commands

from src.interfaces.ds.commands.help import help_command


class Commands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.tree.add_command(help_command)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Commands(bot))
