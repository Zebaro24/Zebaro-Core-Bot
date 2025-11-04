import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties

from app.config import settings
from app.scheduler import scheduler
from app.services.github.github_manager import GithubManager
from app.tg.handlers import get_chat_id, start
from app.tg.handlers.admin import get_job_openings, mongo, server_speed, server_status
from app.tg.handlers.callbacks import docker
from app.tg.notification.job_notification import job_notification
from app.webhooks.setup import get_url_webhook_github, get_url_webhook_telegram, setup_webhook_telegram

logger = logging.getLogger("aiogram.dispatcher")


async def start_bot():
    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    dp.include_router(start.router)
    dp.include_router(get_chat_id.router)

    dp.include_router(server_status.router)
    dp.include_router(server_speed.router)
    dp.include_router(docker.router)
    dp.include_router(mongo.router)

    dp.include_router(get_job_openings.router)

    # scheduler.add_job(job_notification, "cron", hour=10, minute=15, args=[bot])
    # await job_notification(bot)
    scheduler.add_job(job_notification, "cron", hour=12, args=[bot])
    scheduler.add_job(job_notification, "cron", hour=14, args=[bot])
    scheduler.add_job(job_notification, "cron", hour=16, args=[bot])

    github_manager = GithubManager(bot, get_url_webhook_github())
    await github_manager.create_handlers_from_db()

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        if settings.debug:
            await dp.start_polling(bot)
        else:
            setup_webhook_telegram(bot, dp)
            await bot.set_webhook(get_url_webhook_telegram(), drop_pending_updates=True)
            while True:
                await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Telegram bot cancelled, stopping session...")
        if not settings.debug:
            await bot.delete_webhook(drop_pending_updates=True)
        github_manager.delete_all_handlers()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(start_bot())
