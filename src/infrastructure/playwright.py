import asyncio
import logging
from urllib.parse import urlparse

import docker
import docker.errors

from src.config import settings
from src.core.base_infrastructure import BaseInfrastructure

logger = logging.getLogger("infrastructure.playwright")


class PlaywrightInfra(BaseInfrastructure):
    name = "playwright"
    display_name = "Playwright"

    @property
    def container_name(self) -> str:
        return settings.playwright_container_name

    async def start(self) -> None:
        def _start() -> None:
            client = docker.from_env()
            try:
                container = client.containers.get(self.container_name)
                if container.status != "running":
                    container.start()
                    logger.info("Started Playwright container: %s", self.container_name)
                else:
                    logger.debug("Playwright container already running: %s", self.container_name)
            except docker.errors.NotFound:
                logger.error("Playwright container not found: %s", self.container_name)

        await asyncio.to_thread(_start)

    async def stop(self) -> None:
        def _stop() -> None:
            client = docker.from_env()
            try:
                container = client.containers.get(self.container_name)
                if container.status == "running":
                    container.stop()
                    logger.info("Stopped Playwright container: %s", self.container_name)
                else:
                    logger.debug("Playwright container already stopped: %s", self.container_name)
            except docker.errors.NotFound:
                logger.error("Playwright container not found: %s", self.container_name)

        await asyncio.to_thread(_stop)

    async def check_health(self) -> bool:
        parsed = urlparse(settings.playwright_ws_endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 9222
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2.0)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False
