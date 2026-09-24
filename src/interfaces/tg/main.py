import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties

from src.config import settings
from src.core.service_manager import ServiceManager
from src.infrastructure.mongodb import MongoDBInfra
from src.infrastructure.playwright import PlaywrightInfra
from src.interfaces.ds.service import DiscordService
from src.interfaces.tg.handlers import get_chat_id, start
from src.interfaces.tg.handlers.admin import (
    get_job_openings,
    job_stats,
    mongo,
    server_speed,
    server_status,
    services,
    vpn,
)
from src.interfaces.tg.handlers.callbacks import docker, job
from src.interfaces.tg.notification.job_notification import job_notification
from src.interfaces.tg.notification.job_stats_notification import job_stats_notification
from src.interfaces.tg.notification.vpn_notification import vpn_watch, vpn_weekly
from src.interfaces.webhooks.setup import get_url_webhook_github, get_url_webhook_telegram, setup_telegram_webhook
from src.scheduler import scheduler
from src.services.github.service import GithubService
from src.services.job_searcher.service import (
    SEARCH_HOURS,
    WEEKLY_DIGEST_ID,
    JobSearcherService,
    search_job_id,
)
from src.services.vpn.service import WATCH_JOB_ID, WATCH_MINUTES, WEEKLY_JOB_ID, VpnService

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
    dp.include_router(job.router)
    dp.include_router(mongo.router)
    dp.include_router(get_job_openings.router)
    dp.include_router(job_stats.router)
    dp.include_router(vpn.router)
    dp.include_router(services.router)

    # Scheduler jobs (added with IDs so they can be paused/resumed)
    for hour in SEARCH_HOURS:
        scheduler.add_job(job_notification, "cron", hour=hour, args=[bot], id=search_job_id(hour))
    scheduler.add_job(job_stats_notification, "cron", day_of_week="fri", hour=18, args=[bot], id=WEEKLY_DIGEST_ID)
    # First run right away: it also puts wg-easy's firewall hooks in place (vpn_notification.py).
    scheduler.add_job(
        vpn_watch, "interval", minutes=WATCH_MINUTES, args=[bot], id=WATCH_JOB_ID, next_run_time=datetime.now()
    )
    scheduler.add_job(vpn_weekly, "cron", day_of_week="fri", hour=18, minute=5, args=[bot], id=WEEKLY_JOB_ID)

    # Register infrastructure and services with ServiceManager
    sm = ServiceManager.get_instance()
    sm.register_infrastructure(MongoDBInfra())
    sm.register_infrastructure(PlaywrightInfra())
    sm.register_service(JobSearcherService(bot, scheduler))
    sm.register_service(GithubService(bot, get_url_webhook_github()))
    sm.register_service(DiscordService())
    sm.register_service(VpnService(scheduler))

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
