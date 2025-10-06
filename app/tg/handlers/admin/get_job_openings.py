from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from app.tg.middlewares.admin_middleware import AdminMiddleware
from app.tg.notification.job_notification import job_notification

router = Router()
router.message.middleware(AdminMiddleware())


@router.message(Command("get_job_openings"))
async def get_job_openings_command(message: Message):
    await message.answer("Check jobs...")

    await message.bot.send_chat_action(message.chat.id, "typing")

    await job_notification(message.bot)