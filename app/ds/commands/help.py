import discord
from discord import app_commands


@app_commands.command(name="help", description="Помощь")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(f"Привет, {interaction.user.mention}!")
