from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.tg.middlewares.admin_middleware import AdminMiddleware
from app.tg.notification.job_notification import job_notification

router = Router()
router.message.middleware(AdminMiddleware())


@router.message(Command("get_job_openings"))
async def get_job_openings_command(message: Message):
    await message.answer("Check jobs...")

    if bot := message.bot:
        await bot.send_chat_action(message.chat.id, "typing")

        await job_notification(bot)
    else:
        await message.answer("Message bot not found.")
