import asyncio
import logging
from collections.abc import Awaitable

from aiogram import Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import Message

from src.interfaces.tg.formatters.speedtest import format_speedtest_results
from src.services.speedtest.manager import SpeedTestManager

logger = logging.getLogger("tg.handlers.admin.server_speed")

router = Router()

# How often the message is redrawn while a step runs: Telegram allows about one edit a second
# per chat before flood control steps in.
_FRAME_SECONDS = 1.2


async def _redraw(msg: Message, manager: SpeedTestManager, frame: int = 0) -> None:
    try:
        await msg.edit_text(format_speedtest_results(manager, frame))
    except TelegramBadRequest:
        pass  # "message is not modified": the frame came out the same
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
    except TelegramAPIError as e:
        # A redraw that fails must not end the test: the step keeps running, the next frame retries.
        logger.warning("Could not redraw the speed test: %s", e)


async def _animated(msg: Message, manager: SpeedTestManager, step: Awaitable[object]) -> None:
    """Run one step and keep the message moving until it ends."""
    task = asyncio.ensure_future(step)
    frame = 0
    while not task.done():
        await asyncio.wait({task}, timeout=_FRAME_SECONDS)
        frame += 1
        if not task.done():
            await _redraw(msg, manager, frame)
    await task
    await _redraw(msg, manager, frame)


@router.message(Command("server_speed"))
async def server_speed_command(message: Message) -> None:
    logger.info("Speed test requested by user_id=%s", message.from_user.id if message.from_user else "unknown")

    manager = SpeedTestManager()
    msg = await message.answer(format_speedtest_results(manager))

    try:
        await _animated(msg, manager, manager.initialize())
        for step in (manager.prepare, manager.test_download, manager.test_upload):
            if manager.error:
                break
            await _animated(msg, manager, step())
    finally:
        await manager.close()

    logger.info("Speed test complete: %s (error: %s)", manager.results, manager.error)
