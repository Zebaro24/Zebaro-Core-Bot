"""Claude's notifications from the owner's PC — the contract in docs/contracts/notify.md.

Public, through the tunnel (the hook runs on the PC), so the token is the only gate. The body is
parsed by hand after the token check, as in site.py: a tokenless request learns nothing but 401.
"""

import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from src.config import settings
from src.interfaces.tg.notification.notify import clear_session, deliver
from src.services.notify import Notice
from src.services.site_contact import ContactRateLimit

logger = logging.getLogger("webhooks.notify")

router = APIRouter()

# One caller (the owner's hooks); a runaway loop must not flood the chat.
rate_limit = ContactRateLimit(window_s=3600, per_sender=120, overall=120)


def _check_token(request: Request) -> None:
    authorization = request.headers.get("Authorization") or ""
    if not settings.notify_api_token or not secrets.compare_digest(
        authorization, f"Bearer {settings.notify_api_token}"
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def _bot(request: Request):
    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot is not ready")
    return bot


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def notify(request: Request) -> dict[str, bool]:
    _check_token(request)
    try:
        notice = Notice.model_validate_json(await request.body())
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False)) from e
    if not rate_limit.allow("notify", time.monotonic()):
        raise HTTPException(status_code=429, detail="Too many notifications")
    bot = _bot(request)
    try:
        await deliver(bot, notice)
    except Exception:
        logger.exception("Notification for %s/%s was not delivered", notice.project, notice.repo)
        raise HTTPException(status_code=503, detail="Telegram refused the message") from None
    logger.info("Notification delivered: %s/%s %s", notice.project, notice.repo, notice.event)
    return {"ok": True}


@router.delete("")
async def clear(request: Request) -> dict[str, int]:
    """The owner answered in Claude: that session's messages go. An unknown session deletes 0."""
    _check_token(request)
    session = request.query_params.get("session") or ""
    if not 0 < len(session) <= 128:
        raise HTTPException(status_code=422, detail="session: 1 to 128 characters")
    return {"deleted": await clear_session(_bot(request), session)}
