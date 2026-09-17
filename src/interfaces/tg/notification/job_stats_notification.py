import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputRichMessage

from src.config import settings
from src.interfaces.tg.formatters.job_stats import format_weekly_digest, format_weekly_digest_rich
from src.services.job_searcher.stats import get_weekly_stats

logger = logging.getLogger("tg.notification.job_stats")


async def job_stats_notification(bot: Bot) -> None:
    logger.info("Starting job weekly digest")

    stats = await get_weekly_stats()
    try:
        await bot.send_rich_message(
            chat_id=settings.telegram_admin_id,
            rich_message=InputRichMessage(html=format_weekly_digest_rich(stats)),
        )
    except TelegramBadRequest:
        logger.warning("Telegram refused the rich digest, sending the plain version", exc_info=True)
        await bot.send_message(chat_id=settings.telegram_admin_id, text=format_weekly_digest(stats))

    logger.info("Job weekly digest sent")
