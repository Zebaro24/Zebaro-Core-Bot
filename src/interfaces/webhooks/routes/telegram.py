import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger("webhooks.telegram")

router = APIRouter()

# Strong references to running update tasks: the event loop keeps only weak ones,
# so an unreferenced task can be garbage-collected mid-handler.
_update_tasks: set[asyncio.Task[None]] = set()


async def _process_update(bot: Bot, dp: Dispatcher, update: Update) -> None:
    try:
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Unhandled error while processing update id=%s", update.update_id)


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

    # Answer at once and handle the update in the background. Telegram does not send
    # the next update until this one is answered, so a long handler (a job search takes
    # ~45 s) froze the whole bot and its buttons expired while waiting. Always 200 as
    # well: on a 5xx Telegram redelivers the same update over and over.
    task = asyncio.create_task(_process_update(bot, dp, update))
    _update_tasks.add(task)
    task.add_done_callback(_update_tasks.discard)
    return Response(status_code=200)
