import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.interfaces.tg.notification.job_notification import job_notification

logger = logging.getLogger("tg.handlers.admin.get_job_openings")

router = Router()
router.message.middleware(AdminMiddleware())


@router.message(Command("get_job_openings"))
async def get_job_openings_command(message: Message) -> None:
    from src.core.service_manager import ServiceManager

    sm = ServiceManager.get_instance()
    if not sm.is_service_enabled("job_searcher"):
        await message.answer("❌ Сервис Job Searcher выключен")
        return

    logger.info("Manual job search triggered by admin")
    await message.answer("Check jobs...")

    if not message.bot:
        await message.answer("Message bot not found.")
        logger.error("message.bot is None in get_job_openings_command")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    await job_notification(message.bot)
