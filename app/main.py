import asyncio
import logging

from app.db import start_db
from app.tg import start_bot as start_tg
from app.ds import start_bot as start_ds

from app.scheduler import start_scheduler


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    logging.info("Starting Zebaro-Core-Bot...")

    start_scheduler()

    await asyncio.gather(
        start_db(),
        start_tg(),
        start_ds(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Program terminated by user")
