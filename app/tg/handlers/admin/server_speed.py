from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.speedtest_service.manager import SpeedTestManager

router = Router()


@router.message(Command("server_speed"))
async def server_speed_command(message: Message):
    speed_test_manager = SpeedTestManager()
    message = await message.answer(speed_test_manager.get_text())

    await speed_test_manager.prepare()
    await message.edit_text(speed_test_manager.get_text())

    await speed_test_manager.test_download()
    await message.edit_text(speed_test_manager.get_text())

    await speed_test_manager.test_upload()
    await message.edit_text(speed_test_manager.get_text())
