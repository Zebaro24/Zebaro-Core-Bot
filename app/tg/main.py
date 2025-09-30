import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from app.config import settings

from app.tg.handlers import start
from app.tg.handlers.admin import check_server

from app.tg.handlers.callbacks import docker


async def start_bot():
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher()

    dp.include_router(start.router)

    dp.include_router(check_server.router)
    dp.include_router(docker.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_bot())
