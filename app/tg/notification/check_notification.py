from aiogram import Bot

from app.config import settings


async def check_notification(bot: Bot):
    await bot.send_message(chat_id=settings.telegram_admin_id, text="Notification check")