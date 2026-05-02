import logging
from asyncio import sleep

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.config import settings

logger = logging.getLogger("tg.handlers.start")

router = Router()


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    logger.info("Start command from user_id=%s", message.from_user.id if message.from_user else "unknown")

    await message.answer_sticker("CAACAgIAAxkBAAFOAiBo1WrcGZNpGqb-KQABsW7hJDPN-NgAAocCAAJWnb0KQu10K0BX0JA2BA")

    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "typing")
        await sleep(1)

    await message.answer(
        "👋 Привет! Я твой персональный бот-ассистент!\n\n"
        "⚡ Готов автоматизировать скучные задачи, выдавать инфу и иногда шутить 😏\n"
        "🎯 Просто нажимай на кнопки и поехали!\n\n"
        "💡 Подсказка: можно попробовать все команды, чтобы узнать, на что я способен!"
    )

    if message.bot:
        await message.bot.send_chat_action(message.chat.id, "upload_photo")
        await sleep(0.5)

    await message.answer(
        "📌 <b>Доступные команды:</b>\n" "/get_chat_id - Узнать Chat ID и Thread ID 🆔\n",
        message_effect_id="5159385139981059251",
    )

    if message.chat.id in settings.telegram_docker_access_ids:
        await message.answer(
            "🚀 <b>Проекты:</b>\n"
            "/server_status - Проверить работающие контейнеры 🖥️\n"
            "/server_speed - Проверка скорости интернет-соединения 🌐⚡",
            message_effect_id="5104841245755180586",
        )

    if message.chat.id == settings.telegram_admin_id:
        await message.answer(
            "🛠️ <b>Админские фишки:</b>\n"
            "/get_job_openings - Поиск новых вакансий 💼\n"
            "/mongo - Обращение к базе MongoDB 🗄️\n"
            "/services - Управление сервисами и инфрой ⚙️",
            message_effect_id="5046509860389126442",
        )
