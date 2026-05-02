import logging

from src.core.base_service import BaseService

logger = logging.getLogger("services.discord")


class DiscordService(BaseService):
    name = "discord"
    display_name = "Discord"
    infra_deps = []
    needs_restart = True

    async def on_enable(self) -> None:
        logger.info("Discord service marked as enabled (bot restart required)")

    async def on_disable(self) -> None:
        logger.info("Discord service marked as disabled (bot restart required)")
