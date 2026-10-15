"""Monobank's personal webhook: every statement item of every account, as it happens.

Personal webhooks are not signed, so the URL carries a secret. Monobank checks the URL with
a GET when it is set, and switches the webhook off after a few unanswered POSTs — hence a
200 at once, even with the service off (the daily poll picks the item up later then), and
the work in a background task.
"""

import asyncio
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from src.config import settings

logger = logging.getLogger("webhooks.monobank")

router = APIRouter()

_tasks: set[asyncio.Task[None]] = set()


def _check(secret: str) -> None:
    expected = settings.monobank_webhook_secret
    if not expected or not hmac.compare_digest(secret.encode(), str(expected).encode()):
        raise HTTPException(status_code=404)


@router.get("/{secret}")
async def monobank_check(secret: str) -> Response:
    _check(secret)
    return Response(status_code=200)


async def _process(request: Request, account: str, item: dict) -> None:
    from src.db.sql import session
    from src.interfaces.tg.notification.spotify_notification import handle
    from src.services.spotify.sync import ingest

    try:
        async with session() as s, s.begin():
            result = await ingest(s, account, [item])
        bot = getattr(request.app.state, "bot", None)
        if bot:
            await handle(bot, result)
    except Exception:
        logger.exception("Monobank webhook item %s failed", item.get("id"))


@router.post("/{secret}")
async def monobank_webhook(secret: str, request: Request) -> Response:
    _check(secret)
    from src.core.service_manager import ServiceManager

    try:
        payload = await request.json()
        data = payload["data"]
        account, item = str(data["account"]), dict(data["statementItem"])
        if not all(key in item for key in ("id", "time", "amount")):
            raise KeyError("statementItem")
    except Exception:
        logger.warning("Monobank webhook: unexpected payload")
        return Response(status_code=200)
    if payload.get("type") != "StatementItem" or not ServiceManager.get_instance().is_service_enabled("spotify"):
        return Response(status_code=200)
    task = asyncio.create_task(_process(request, account, item))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return Response(status_code=200)
