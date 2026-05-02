import asyncio
import logging

import docker
import docker.errors

from src.config import settings
from src.core.base_infrastructure import BaseInfrastructure

logger = logging.getLogger("infrastructure.mongodb")


class MongoDBInfra(BaseInfrastructure):
    name = "mongodb"
    display_name = "MongoDB"

    @property
    def container_name(self) -> str:
        return settings.mongodb_container_name

    async def start(self) -> None:
        def _start() -> None:
            client = docker.from_env()
            try:
                container = client.containers.get(self.container_name)
                if container.status != "running":
                    container.start()
                    logger.info("Started MongoDB container: %s", self.container_name)
                else:
                    logger.debug("MongoDB container already running: %s", self.container_name)
            except docker.errors.NotFound:
                logger.error("MongoDB container not found: %s", self.container_name)

        await asyncio.to_thread(_start)

    async def stop(self) -> None:
        def _stop() -> None:
            client = docker.from_env()
            try:
                container = client.containers.get(self.container_name)
                if container.status == "running":
                    container.stop()
                    logger.info("Stopped MongoDB container: %s", self.container_name)
                else:
                    logger.debug("MongoDB container already stopped: %s", self.container_name)
            except docker.errors.NotFound:
                logger.error("MongoDB container not found: %s", self.container_name)

        await asyncio.to_thread(_stop)

    async def check_health(self) -> bool:
        from src.db.client import client as mongo_client

        try:
            await asyncio.wait_for(mongo_client.admin.command("ping"), timeout=2.0)
            return True
        except Exception:
            return False
