import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties

from src.config import settings
from src.core.service_manager import ServiceManager
from src.infrastructure.mongodb import MongoDBInfra
from src.infrastructure.playwright import PlaywrightInfra
from src.interfaces.ds.service import DiscordService
from src.interfaces.tg.handlers import get_chat_id, start
from src.interfaces.tg.handlers.admin import get_job_openings, mongo, server_speed, server_status, services
from src.interfaces.tg.handlers.callbacks import docker
from src.interfaces.tg.notification.job_notification import job_notification
from src.interfaces.webhooks.setup import get_url_webhook_github, get_url_webhook_telegram, setup_telegram_webhook
from src.scheduler import scheduler
from src.services.github.service import GithubService
from src.services.job_searcher.service import JobSearcherService

logger = logging.getLogger("tg.main")


async def start_bot() -> None:
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    # Routers
    dp.include_router(start.router)
    dp.include_router(get_chat_id.router)
    dp.include_router(server_status.router)
    dp.include_router(server_speed.router)
    dp.include_router(docker.router)
    dp.include_router(mongo.router)
    dp.include_router(get_job_openings.router)
    dp.include_router(services.router)

    # Scheduler jobs (added with IDs so they can be paused/resumed)
    scheduler.add_job(job_notification, "cron", hour=12, args=[bot], id="job_notification_12")
    scheduler.add_job(job_notification, "cron", hour=14, args=[bot], id="job_notification_14")
    scheduler.add_job(job_notification, "cron", hour=16, args=[bot], id="job_notification_16")

    # Register infrastructure and services with ServiceManager
    sm = ServiceManager.get_instance()
    sm.register_infrastructure(MongoDBInfra())
    sm.register_infrastructure(PlaywrightInfra())
    sm.register_service(JobSearcherService(bot, scheduler))
    sm.register_service(GithubService(bot, get_url_webhook_github()))
    sm.register_service(DiscordService())

    # Apply saved state: start/stop containers, enable/disable services
    await sm.apply_state()

    # Expose bot and dp to webhook routes via app.state
    # github_manager is set by GithubService.on_enable() during apply_state
    setup_telegram_webhook(bot, dp)

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        if settings.debug:
            logger.info("Starting Telegram bot in polling mode")
            await dp.start_polling(bot)
        else:
            logger.info("Starting Telegram bot in webhook mode")
            await bot.set_webhook(get_url_webhook_telegram(), drop_pending_updates=True)
            while True:
                await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Telegram bot cancelled, shutting down...")
        if not settings.debug:
            await bot.delete_webhook(drop_pending_updates=True)
        # Clean up GitHub handlers if service was enabled
        github_service = sm.all_services.get("github")
        if github_service and hasattr(github_service, "_manager") and github_service._manager:
            await github_service._manager.delete_all_handlers()
        await bot.session.close()
