import hashlib
import hmac
import logging

from aiogram import Bot

from src.config import settings
from src.db.client import github_notification_collection
from src.services.github.event_handler import GithubRepoEvent
from src.services.github.webhook import GithubRepoWebhook

logger = logging.getLogger("github.manager")


class GithubManager:
    """Coordinates GitHub webhook lifecycle and event routing.

    Note: github_repo_webhooks and github_repo_events are instance-level dicts,
    NOT class-level. Each GithubManager instance manages its own set of repos.
    """

    def __init__(self, bot: Bot, github_webhook_url: str) -> None:
        self.bot = bot
        self.github_webhook_url = github_webhook_url
        self.github_repo_webhooks: dict[str, GithubRepoWebhook] = {}
        self.github_repo_events: dict[str, GithubRepoEvent] = {}

    @staticmethod
    def verify_signature(body: bytes, signature: str) -> bool:
        mac = hmac.new(settings.personal_github_secret.encode(), msg=body, digestmod=hashlib.sha256)
        expected_sig = "sha256=" + mac.hexdigest()
        return hmac.compare_digest(expected_sig, signature)

    async def handle(self, full_repo_name: str, event: str, payload: dict) -> None:
        if full_repo_name not in self.github_repo_events:
            logger.warning("Event for %s not found", full_repo_name)
            return
        await self.github_repo_events[full_repo_name].handle(event, payload)

    async def create_handler(self, full_repo_name: str, tg_chat_id: int, thread_id: int | None = None) -> None:
        webhook = GithubRepoWebhook(full_repo_name, self.github_webhook_url)
        await webhook.enable_webhook()

        event_handler = GithubRepoEvent(full_repo_name, self.bot, tg_chat_id, thread_id)

        self.github_repo_webhooks[full_repo_name] = webhook
        self.github_repo_events[full_repo_name] = event_handler
        logger.info("Handler created for %s (chat_id=%s)", full_repo_name, tg_chat_id)

    async def delete_handler(self, full_repo_name: str) -> None:
        if full_repo_name not in self.github_repo_webhooks:
            logger.warning("Webhook for %s not found", full_repo_name)
            return
        await self.github_repo_webhooks[full_repo_name].disable_webhook()
        del self.github_repo_webhooks[full_repo_name]
        del self.github_repo_events[full_repo_name]
        logger.info("Handler deleted for %s", full_repo_name)

    async def delete_all_handlers(self) -> None:
        for full_repo_name in list(self.github_repo_webhooks.keys()):
            await self.delete_handler(full_repo_name)
        logger.info("All handlers deleted")

    def get_webhook(self, full_repo_name: str) -> GithubRepoWebhook | None:
        if full_repo_name not in self.github_repo_webhooks:
            logger.warning("Webhook for %s not found", full_repo_name)
            return None
        return self.github_repo_webhooks[full_repo_name]

    def get_event(self, full_repo_name: str) -> GithubRepoEvent | None:
        if full_repo_name not in self.github_repo_events:
            logger.warning("Event handler for %s not found", full_repo_name)
            return None
        return self.github_repo_events[full_repo_name]

    async def create_handlers_from_db(self) -> None:
        try:
            records = await github_notification_collection.find().to_list(length=None)
            for rec in records:
                await self.create_handler(
                    full_repo_name=rec["full_repo_name"],
                    tg_chat_id=rec["tg_chat_id"],
                    thread_id=rec.get("thread_id"),
                )
            logger.info("Loaded %d handlers from DB", len(records))
        except Exception as e:
            logger.warning("Failed to load GitHub handlers from DB, starting empty: %s", e)

    @staticmethod
    async def add_notification_to_db(full_repo_name: str, tg_chat_id: int, thread_id: int | None = None) -> None:
        existing = await github_notification_collection.find_one(
            {"full_repo_name": full_repo_name, "tg_chat_id": tg_chat_id, "thread_id": thread_id}
        )
        if not existing:
            await github_notification_collection.insert_one(
                {"full_repo_name": full_repo_name, "tg_chat_id": tg_chat_id, "thread_id": thread_id}
            )
            logger.info("Notification added to DB for %s", full_repo_name)
        else:
            logger.debug("Notification already exists for %s", full_repo_name)
