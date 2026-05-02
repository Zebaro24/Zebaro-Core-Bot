import logging

import httpx

from src.config import settings

logger = logging.getLogger("github.webhook")


class GithubRepoWebhook:
    def __init__(self, full_repo_name: str, github_webhook_url: str, events: list[str] | None = None) -> None:
        self.full_repo_name = full_repo_name
        self.events = events or ["push", "pull_request", "workflow_run"]
        self.headers = {"Authorization": f"token {settings.personal_github_token}"}
        self.github_webhook_url = github_webhook_url
        self.secret = settings.personal_github_secret
        self.hook_id: str | None = None

    async def _get_existing_hook(self) -> dict | None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.github.com/repos/{self.full_repo_name}/hooks",
                headers=self.headers,
                timeout=5,
            )
        hooks = resp.json()
        for hook in hooks:
            if hook.get("config", {}).get("url") == self.github_webhook_url:
                return dict(hook)
        return None

    async def enable_webhook(self) -> None:
        existing_hook = await self._get_existing_hook()

        if existing_hook:
            config = existing_hook.get("config", {})
            needs_update = (
                config.get("secret") != self.secret
                or config.get("content_type") != "json"
                or set(existing_hook.get("events", [])) != set(self.events)
            )
            if needs_update:
                logger.info("Updating webhook for %s", self.full_repo_name)
                async with httpx.AsyncClient() as client:
                    r = await client.patch(
                        f"https://api.github.com/repos/{self.full_repo_name}/hooks/{existing_hook['id']}",
                        headers=self.headers,
                        json={
                            "config": {
                                "url": self.github_webhook_url,
                                "content_type": "json",
                                "secret": self.secret,
                                "insecure_ssl": "0",
                            },
                            "events": self.events,
                            "active": True,
                        },
                        timeout=5,
                    )
                if r.status_code in (200, 201):
                    logger.info("Webhook updated for %s", self.full_repo_name)
                else:
                    logger.error("Failed to update webhook for %s: %s", self.full_repo_name, r.text)
            else:
                logger.info("Webhook already up-to-date for %s", self.full_repo_name)
            return

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://api.github.com/repos/{self.full_repo_name}/hooks",
                json={
                    "name": "web",
                    "active": True,
                    "events": self.events,
                    "config": {
                        "url": self.github_webhook_url,
                        "content_type": "json",
                        "secret": self.secret,
                        "insecure_ssl": "0",
                    },
                },
                headers=self.headers,
                timeout=5,
            )
        if r.status_code in (200, 201):
            logger.info("Webhook created for %s", self.full_repo_name)
        else:
            logger.error("Failed to create webhook for %s: %s", self.full_repo_name, r.text)

    async def disable_webhook(self) -> None:
        existing_hook = await self._get_existing_hook()
        if not existing_hook:
            logger.warning("No webhook found to disable for %s", self.full_repo_name)
            return
        async with httpx.AsyncClient() as client:
            r = await client.delete(
                f"https://api.github.com/repos/{self.full_repo_name}/hooks/{existing_hook['id']}",
                headers=self.headers,
                timeout=5,
            )
        if r.status_code == 204:
            logger.info("Webhook deleted for %s", self.full_repo_name)
        else:
            logger.error("Failed to delete webhook for %s: %s", self.full_repo_name, r.text)
