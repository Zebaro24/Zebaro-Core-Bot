import hashlib
import hmac
import logging

from aiogram import Bot

from app.config import settings
from app.db.client import github_notification_collection
from app.services.github.github_repo_event import GithubRepoEvent
from app.services.github.github_repo_webhook import GithubRepoWebhook

logger = logging.getLogger("github.manager")


class GithubManager:
    github_repo_webhooks = {}
    github_repo_events = {}

    def __init__(self, bot: Bot, github_webhook_url: str):
        self.bot = bot
        self.github_webhook_url = github_webhook_url

    @staticmethod
    def verify_signature(body, signature):
        mac = hmac.new(settings.personal_github_secret.encode(), msg=body, digestmod=hashlib.sha256)
        expected_sig = "sha256=" + mac.hexdigest()
        return hmac.compare_digest(expected_sig, signature)

    @staticmethod
    async def handle(full_repo_name, event, payload):
        if full_repo_name not in GithubManager.github_repo_events:
            logger.warning(f"Event for {full_repo_name} not found")
            return

        await GithubManager.github_repo_events[full_repo_name].handle(event, payload)

    def create_handler(self, full_repo_name, tg_chat_id, thread_id=None):
        github_repo_webhook = GithubRepoWebhook(full_repo_name, self.github_webhook_url)
        github_repo_webhook.enable_webhook()

        github_repo_event = GithubRepoEvent(full_repo_name, self.bot, tg_chat_id, thread_id)

        self.github_repo_webhooks[full_repo_name] = github_repo_webhook
        self.github_repo_events[full_repo_name] = github_repo_event

    def delete_handler(self, full_repo_name):
        if full_repo_name not in self.github_repo_webhooks:
            logger.warning(f"Webhook for {full_repo_name} not found")
            return

        self.github_repo_webhooks[full_repo_name].disable_webhook()
        del self.github_repo_webhooks[full_repo_name]
        del self.github_repo_events[full_repo_name]

    def delete_all_handlers(self):
        for full_repo_name in self.github_repo_webhooks:
            self.delete_handler(full_repo_name)

    def get_webhook(self, full_repo_name):
        if full_repo_name not in self.github_repo_webhooks:
            logger.warning(f"Webhook for {full_repo_name} not found")
            return None

        return self.github_repo_webhooks[full_repo_name]

    def get_event(self, full_repo_name):
        if full_repo_name not in self.github_repo_events:
            logger.warning(f"Event for {full_repo_name} not found")
            return None

        return self.github_repo_events[full_repo_name]

    async def create_handlers_from_db(self):
        records = await github_notification_collection.find().to_list(length=None)

        for rec in records:
            full_repo_name = rec["full_repo_name"]
            tg_chat_id = rec["tg_chat_id"]
            thread_id = rec["thread_id"]
            self.create_handler(full_repo_name, tg_chat_id, thread_id)

        logger.info("All handlers from DB have been created")

    @staticmethod
    async def add_notification_to_db(full_repo_name, tg_chat_id, thread_id=None):
        existing = await github_notification_collection.find_one(
            {
                "full_repo_name": full_repo_name,
                "tg_chat_id": tg_chat_id,
                "thread_id": thread_id,
            }
        )
        if not existing:
            await github_notification_collection.insert_one(
                {
                    "full_repo_name": full_repo_name,
                    "tg_chat_id": tg_chat_id,
                    "thread_id": thread_id,
                }
            )


if __name__ == "__main__":
    import asyncio

    async def add_notification_to_db():
        await GithubManager.add_notification_to_db("Zebaro24/test", 771348519, 0)

    asyncio.run(add_notification_to_db())
