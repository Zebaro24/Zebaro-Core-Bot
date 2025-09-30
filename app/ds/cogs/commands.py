from discord.ext import commands

from app.ds.commands.help import help_command


class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        bot.tree.add_command(help_command)


async def setup(bot):
    await bot.add_cog(Commands(bot))
