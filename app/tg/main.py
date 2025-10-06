import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from app.config import settings

from app.tg.handlers import start
from app.tg.handlers.admin import check_server

from app.tg.handlers.callbacks import docker

from app.tg.notification.check_notification import check_notification

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

    scheduler.add_job(check_notification, "cron", hour=17, minute=52 , args=[bot])
    scheduler.add_job(check_notification, "cron", hour=17, minute=53 , args=[bot])

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Telegram bot cancelled, stopping session...")
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(start_bot())
