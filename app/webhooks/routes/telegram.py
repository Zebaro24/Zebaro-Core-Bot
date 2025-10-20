from aiogram.types import Update
from aiogram import Bot, Dispatcher
from fastapi import APIRouter, Request, Response, HTTPException

router = APIRouter()

bot: Bot | None = None
dp: Dispatcher | None = None


@router.post("")
async def root(request: Request):
    if not bot or not dp:
        raise HTTPException(status_code=503, detail="Bot not ready")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        update = Update.model_validate(data)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid update payload")

    await dp.feed_update(bot, update)
    return Response(status_code=200)
