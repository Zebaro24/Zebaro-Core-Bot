from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart
from asyncio import sleep
from app.config import settings

router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer_sticker("CAACAgIAAxkBAAFOAiBo1WrcGZNpGqb-KQABsW7hJDPN-NgAAocCAAJWnb0KQu10K0BX0JA2BA")

    await message.bot.send_chat_action(message.chat.id, "typing")
    await sleep(1)

    text = (
        "Привет, я твой персональный бот-ассистент! 🚀\n"
        "Готов автоматизировать скучные дела, выдавать инфу и иногда шутить (иногда — лучше не проверять 😏).\n\n"
        "Нажимай на кнопки ниже и давай начнём! ⚡"
    )
    await message.answer(text)

    if message.chat.id in settings.telegram_docker_access_ids:
        text_commands = "/check_server - Проверить работающие контейнеры"
        await message.answer(text_commands)

    if message.chat.id == settings.telegram_admin_id:
        text_commands = "/get_job_openings - Поиск новых вакансий\n"
        text_commands += "/mongo - Обращение в MongoDB\n"
        await message.answer(text_commands)
