import logging
import requests

from app.config import settings

logger = logging.getLogger("github.webhook")


class GithubRepoWebhook:
    def __init__(self, full_repo_name: str, github_webhook_url, events: list | None = None):
        self.full_repo_name = full_repo_name

        if events is None:
            self.events = ["push", "pull_request", "workflow_run"]
        else:
            self.events = events

        self.headers = {"Authorization": f"token {settings.personal_github_token}"}
        self.github_webhook_url = github_webhook_url
        self.secret = settings.personal_github_secret

        self.hook_id: str | None = None

    def enable_webhook(self):
        hooks = requests.get(
            f"https://api.github.com/repos/{self.full_repo_name}/hooks",
            headers=self.headers
        ).json()

        existing_hook = None
        for hook in hooks:
            config = hook.get("config", {})
            if config.get("url") == self.github_webhook_url:
                existing_hook = hook
                break

        if existing_hook:
            config = existing_hook.get("config", {})
            needs_update = (
                    config.get("secret") != self.secret or
                    config.get("content_type") != "json" or
                    set(existing_hook.get("events", [])) != set(self.events)
            )

            if needs_update:
                logger.info(f"Обновляем webhook для {self.full_repo_name}")
                payload = {
                    "config": {
                        "url": self.github_webhook_url,
                        "content_type": "json",
                        "secret": self.secret,
                        "insecure_ssl": "0"
                    },
                    "events": self.events,
                    "active": True
                }
                r = requests.patch(
                    f"https://api.github.com/repos/{self.full_repo_name}/hooks/{existing_hook['id']}",
                    headers=self.headers,
                    json=payload
                )
                if r.status_code in [200, 201]:
                    logger.info(f"Webhook обновлён для {self.full_repo_name}")
                else:
                    logger.error(f"Ошибка при обновлении webhook для {self.full_repo_name}: {r.text}")
            else:
                logger.info(f"Webhook уже актуален для {self.full_repo_name}")
            return

        payload = {
            "name": "web",
            "active": True,
            "events": self.events,
            "config": {
                "url": self.github_webhook_url,
                "content_type": "json",
                "secret": self.secret,
                "insecure_ssl": "0"
            }
        }

        r = requests.post(
            f"https://api.github.com/repos/{self.full_repo_name}/hooks",
            json=payload,
            headers=self.headers
        )
        if r.status_code in [200, 201]:
            logger.info(f"Webhook создан для {self.full_repo_name}")
        else:
            logger.error(f"Ошибка при создании webhook для {self.full_repo_name}: {r.text}")

    def disable_webhook(self):
        hooks = requests.get(
            f"https://api.github.com/repos/{self.full_repo_name}/hooks",
            headers=self.headers
        ).json()

        for hook in hooks:
            if hook["config"].get("url") == self.github_webhook_url:
                hook_id = hook["id"]
                r = requests.delete(
                    f"https://api.github.com/repos/{self.full_repo_name}/hooks/{hook_id}",
                    headers=self.headers
                )
                if r.status_code == 204:
                    logger.info(f"Webhook удалён из {self.full_repo_name}")
                else:
                    logger.error(f"Ошибка при удалении webhook из {self.full_repo_name}: {r.text}")
