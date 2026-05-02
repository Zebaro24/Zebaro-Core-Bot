from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot

from src.core.base_service import BaseService

if TYPE_CHECKING:
    from src.services.github.manager import GithubManager

logger = logging.getLogger("services.github")


class GithubService(BaseService):
    name = "github"
    display_name = "GitHub"
    infra_deps = ["mongodb"]

    def __init__(self, bot: Bot, webhook_url: str) -> None:
        self._bot = bot
        self._webhook_url = webhook_url
        self._manager: GithubManager | None = None

    async def on_enable(self) -> None:
        from src.interfaces.webhooks.main import app
        from src.services.github.manager import GithubManager

        if self._manager is None:
            self._manager = GithubManager(self._bot, self._webhook_url)
            await self._manager.create_handlers_from_db()

        app.state.github_manager = self._manager
        logger.info("GitHub service enabled (%d handlers)", len(self._manager.github_repo_webhooks))

    async def on_disable(self) -> None:
        from src.interfaces.webhooks.main import app

        app.state.github_manager = None
        logger.info("GitHub service disabled")
