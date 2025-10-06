import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from app.config import settings

from app.tg.handlers import start
from app.tg.handlers.admin import check_server
from app.tg.handlers.admin import get_job_openings

from app.tg.handlers.callbacks import docker

from app.tg.notification.job_notification import job_notification

from app.scheduler import scheduler

logger = logging.getLogger('aiogram.dispatcher')

async def start_bot():
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher()

    dp.include_router(start.router)

    dp.include_router(check_server.router)
    dp.include_router(docker.router)

    dp.include_router(get_job_openings.router)

    # scheduler.add_job(job_notification, "cron", hour=10, minute=15 , args=[bot])
    # await job_notification(bot)
    scheduler.add_job(job_notification, "cron", hour=12, args=[bot])
    scheduler.add_job(job_notification, "cron", hour=14, args=[bot])
    scheduler.add_job(job_notification, "cron", hour=16, args=[bot])

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Telegram bot cancelled, stopping session...")
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(start_bot())
