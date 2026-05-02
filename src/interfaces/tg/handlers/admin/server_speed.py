import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.interfaces.tg.formatters.speedtest import format_speedtest_results
from src.services.speedtest.manager import SpeedTestManager

logger = logging.getLogger("tg.handlers.admin.server_speed")

router = Router()


@router.message(Command("server_speed"))
async def server_speed_command(message: Message) -> None:
    logger.info("Speed test requested by user_id=%s", message.from_user.id if message.from_user else "unknown")

    manager = SpeedTestManager()
    msg = await message.answer(format_speedtest_results(manager))

    if not await manager.initialize():
        await msg.edit_text(format_speedtest_results(manager))
        return

    await manager.prepare()
    await msg.edit_text(format_speedtest_results(manager))

    await manager.test_download()
    await msg.edit_text(format_speedtest_results(manager))

    await manager.test_upload()
    await msg.edit_text(format_speedtest_results(manager))

    logger.info("Speed test complete: %s", manager.results)
