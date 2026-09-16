import logging

from aiogram import Bot

from src.config import settings
from src.interfaces.tg.formatters.job_stats import format_weekly_digest
from src.services.job_searcher.stats import get_weekly_stats

logger = logging.getLogger("tg.notification.job_stats")


async def job_stats_notification(bot: Bot) -> None:
    logger.info("Starting job weekly digest")

    stats = await get_weekly_stats()
    await bot.send_message(chat_id=settings.telegram_admin_id, text=format_weekly_digest(stats))

    logger.info("Job weekly digest sent")
