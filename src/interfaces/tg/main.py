import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties

from src.config import settings
from src.core.service_manager import ServiceManager
from src.infrastructure.mongodb import MongoDBInfra
from src.infrastructure.playwright import PlaywrightInfra
from src.interfaces.ds.service import DiscordService
from src.interfaces.tg.commands import set_commands
from src.interfaces.tg.handlers import get_chat_id, spotify_member, start
from src.interfaces.tg.handlers.admin import (
    get_job_openings,
    github,
    job_stats,
    mongo,
    server_speed,
    server_status,
    services,
    spotify,
    vpn,
)
from src.interfaces.tg.handlers.callbacks import docker, job
from src.interfaces.tg.notification import github as github_notification
from src.interfaces.tg.notification import notify
from src.interfaces.tg.notification.job_notification import job_notification
from src.interfaces.tg.notification.job_stats_notification import job_stats_notification
from src.interfaces.tg.notification.job_status import SYNC_JOB_ID, SYNC_MINUTES, sync_job_messages
from src.interfaces.tg.notification.spotify_notification import (
    ensure_webhook,
    spotify_bootstrap,
    spotify_poll,
    spotify_tick,
)
from src.interfaces.tg.notification.vpn_notification import vpn_watch, vpn_weekly
from src.interfaces.webhooks.setup import get_url_webhook_telegram, setup_telegram_webhook
from src.scheduler import scheduler
from src.services.github.api import GithubApp
from src.services.github.service import GithubService
from src.services.job_searcher.service import (
    SEARCH_HOURS,
    WEEKLY_DIGEST_ID,
    JobSearcherService,
    search_job_id,
)
from src.services.job_searcher.silence import SILENCE_HOUR, SILENCE_JOB_ID, silence_job
from src.services.notify import SWEEP_JOB_ID, SWEEP_MINUTES
from src.services.spotify.schedule import EVENING, MORNING
from src.services.spotify.service import (
    EVENING_HOUR,
    EVENING_JOB_ID,
    MORNING_HOUR,
    MORNING_JOB_ID,
    POLL_HOUR,
    POLL_JOB_ID,
    POLL_MINUTE,
    SpotifyService,
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
    # Before /start (the invite is /start sp_<code>) and the admin routers (they refuse others).
    dp.include_router(spotify_member.router)
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
    dp.include_router(spotify.router)
    dp.include_router(services.router)
    dp.include_router(notify.router)
    dp.include_router(github.router)
    dp.include_router(github.topics_router)
    dp.include_router(github_notification.router)

    # Scheduler jobs (added with IDs so they can be paused/resumed)
    for hour in SEARCH_HOURS:
        scheduler.add_job(job_notification, "cron", hour=hour, args=[bot], id=search_job_id(hour))
    scheduler.add_job(job_stats_notification, "cron", day_of_week="fri", hour=18, args=[bot], id=WEEKLY_DIGEST_ID)
    # S3: applications nobody answered → "no_response"; does nothing until the history backfill ran.
    scheduler.add_job(silence_job, "cron", hour=SILENCE_HOUR, id=SILENCE_JOB_ID)
    # Status changes made through the Jobs API → Telegram. Not paused with the job searcher: the API
    # and this loop need MongoDB only. Picks up what a restart left pending.
    scheduler.add_job(
        sync_job_messages, "interval", minutes=SYNC_MINUTES, args=[bot], id=SYNC_JOB_ID,
        max_instances=1, coalesce=True, next_run_time=datetime.now() + timedelta(seconds=20),
    )  # fmt: skip
    # First run right away: it also puts wg-easy's firewall hooks in place (vpn_notification.py).
    scheduler.add_job(
        vpn_watch, "interval", minutes=WATCH_MINUTES, args=[bot], id=WATCH_JOB_ID, next_run_time=datetime.now()
    )
    scheduler.add_job(vpn_weekly, "cron", day_of_week="fri", hour=18, minute=5, args=[bot], id=WEEKLY_JOB_ID)
    scheduler.add_job(spotify_poll, "cron", hour=POLL_HOUR, minute=POLL_MINUTE, args=[bot], id=POLL_JOB_ID)
    scheduler.add_job(spotify_tick, "cron", hour=MORNING_HOUR, args=[bot, MORNING], id=MORNING_JOB_ID)
    scheduler.add_job(spotify_tick, "cron", hour=EVENING_HOUR, args=[bot, EVENING], id=EVENING_JOB_ID)
    # Claude's notifications nobody cleared go after 12 hours (services/notify.py).
    scheduler.add_job(
        notify.notify_sweep, "interval", minutes=SWEEP_MINUTES, args=[bot], id=SWEEP_JOB_ID,
        max_instances=1, coalesce=True,
    )  # fmt: skip
    # GitHub: "снова зелёный" messages go an hour later; old live-message records are pruned.
    scheduler.add_job(
        github_notification.github_sweep, "interval", minutes=github_notification.SWEEP_MINUTES, args=[bot],
        id=github_notification.SWEEP_JOB_ID, max_instances=1, coalesce=True,
    )  # fmt: skip
    # Once, when the web server is surely up: Monobank checks the URL the moment it is set.
    scheduler.add_job(ensure_webhook, "date", run_date=datetime.now() + timedelta(seconds=30), args=[bot])
    # After the webhook check: both use client-info, which answers once a minute.
    scheduler.add_job(spotify_bootstrap, "date", run_date=datetime.now() + timedelta(seconds=100), args=[bot])

    # Register infrastructure and services with ServiceManager
    sm = ServiceManager.get_instance()
    sm.register_infrastructure(MongoDBInfra())
    sm.register_infrastructure(PlaywrightInfra())
    sm.register_service(JobSearcherService(bot, scheduler))
    # One App for the service, its buttons and /github: the installation token is shared.
    github_app = GithubApp(settings.gh_app_id, settings.gh_app_key, settings.gh_owner)
    github.use_app(github_app)
    github_notification.use_app(github_app)
    sm.register_service(GithubService(github_notification.make_deliver(bot, github_app), github_app))
    sm.register_service(DiscordService())
    sm.register_service(VpnService(scheduler))
    sm.register_service(SpotifyService(scheduler))

    # Apply saved state: start/stop containers, enable/disable services
    await sm.apply_state()

    # Expose bot and dp to webhook routes via app.state
    setup_telegram_webhook(bot, dp)

    await bot.delete_webhook(drop_pending_updates=True)
    await set_commands(bot)

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
        await github_app.close()
        await bot.session.close()
