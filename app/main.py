import asyncio
import logging

from app.tg import start_bot as start_tg
from app.ds import start_bot as start_ds
from app.scheduler import start_scheduler


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    await asyncio.gather(
        start_tg(),
        start_ds(),
        start_scheduler(),
    )

if __name__ == "__main__":
    asyncio.run(main())
