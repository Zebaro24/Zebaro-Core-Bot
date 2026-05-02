import asyncio
import logging

from src.core.service_manager import ServiceManager
from src.db import start_db
from src.interfaces.ds.main import start_bot as start_ds
from src.interfaces.tg.main import start_bot as start_tg
from src.interfaces.webhooks.main import start_webhooks
from src.scheduler import start_scheduler


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    logging.info("Starting Zebaro-Core-Bot...")

    # Load saved service state before anything starts
    ServiceManager.get_instance().load_state()

    start_scheduler()

    tasks: list = [
        start_db(),
        start_tg(),
        start_webhooks(),
    ]

    # Discord is optional — skip if disabled in saved state
    if ServiceManager.get_instance().is_service_enabled("discord"):
        tasks.append(start_ds())
    else:
        logging.info("Discord service is disabled, skipping")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Program terminated by user")
