import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger("webhooks.telegram")

router = APIRouter()


@router.post("")
async def telegram_webhook(request: Request) -> Response:
    bot: Bot | None = getattr(request.app.state, "bot", None)
    dp: Dispatcher | None = getattr(request.app.state, "dp", None)

    if not bot or not dp:
        logger.error("Telegram bot/dispatcher not initialized in app.state")
        raise HTTPException(status_code=503, detail="Bot not ready")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        update = Update.model_validate(data)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid update payload")

    try:
        await dp.feed_update(bot, update)
    except Exception:
        # Отвечаем 200 даже при падении хендлера: на 5xx Telegram повторяет тот же апдейт
        # по кругу, и упавшая команда перезапускается снова и снова.
        logger.exception("Unhandled error while processing update id=%s", update.update_id)
    return Response(status_code=200)
