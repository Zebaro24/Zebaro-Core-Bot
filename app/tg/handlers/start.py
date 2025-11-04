from asyncio import sleep

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import settings

router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer_sticker("CAACAgIAAxkBAAFOAiBo1WrcGZNpGqb-KQABsW7hJDPN-NgAAocCAAJWnb0KQu10K0BX0JA2BA")

    bot = message.bot
    if bot:
        await bot.send_chat_action(message.chat.id, "typing")
        await sleep(1)

    text = (
        "👋 Привет! Я твой персональный бот-ассистент!\n\n"
        "⚡ Готов автоматизировать скучные задачи, выдавать инфу и иногда шутить 😏\n"
        "🎯 Просто нажимай на кнопки и поехали!\n\n"
        "💡 Подсказка: можно попробовать все команды, чтобы узнать, на что я способен!"
    )
    await message.answer(text)

    if bot:
        await bot.send_chat_action(message.chat.id, "upload_photo")
        await sleep(0.5)

    text_commands_all = "📌 <b>Доступные команды:</b>\n" "/get_chat_id - Узнать Chat ID и Thread ID 🆔\n"
    await message.answer(text_commands_all, message_effect_id="5159385139981059251")

    if message.chat.id in settings.telegram_docker_access_ids:
        text_commands = (
            "🚀 <b>Проекты:</b>\n"
            "/server_status - Проверить работающие контейнеры 🖥️\n"
            "/server_speed - Проверка скорости интернет-соединения 🌐⚡"
        )
        await message.answer(text_commands, message_effect_id="5104841245755180586")

    if message.chat.id == settings.telegram_admin_id:
        admin_commands = (
            "🛠️ <b>Админские фишки:</b>\n"
            "/get_job_openings - Поиск новых вакансий 💼\n"
            "/mongo - Обращение к базе MongoDB 🗄️"
        )
        await message.answer(admin_commands, message_effect_id="5046509860389126442")
