import discord
from discord import app_commands


@app_commands.command(name="help", description="Помощь")
async def help_command(interaction: discord.Interaction) -> None:
    # TODO: Expand with actual help text listing all available commands.
    await interaction.response.send_message(f"Привет, {interaction.user.mention}!")
