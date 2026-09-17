import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.interfaces.tg.middlewares.admin import AdminMiddleware
from src.interfaces.tg.notification.job_stats_notification import send_stats_digest

logger = logging.getLogger("tg.handlers.admin.job_stats")

router = Router()
router.message.middleware(AdminMiddleware())

DEFAULT_DAYS = 7
MAX_DAYS = 180


def parse_days(text: str) -> int:
    """`/job_stats 30` — the period in days; anything else means a week."""
    parts = text.split()
    if len(parts) > 1 and parts[1].isdigit():
        return max(1, min(int(parts[1]), MAX_DAYS))
    return DEFAULT_DAYS


@router.message(Command("job_stats"))
async def job_stats_command(message: Message) -> None:
    days = parse_days(message.text or "")
    logger.info("Job stats requested for %d days", days)

    if not message.bot:
        logger.error("message.bot is None in job_stats_command")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        await send_stats_digest(message.bot, message.chat.id, days)
    except Exception:
        logger.exception("Job stats failed")
        await message.answer("💀 Не смог собрать статистику, смотри логи")
