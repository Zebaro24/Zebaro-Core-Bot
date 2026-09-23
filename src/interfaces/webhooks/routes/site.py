import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, status

from src.config import settings
from src.interfaces.tg.formatters.site_contact import site_contact_to_html
from src.interfaces.tg.keyboards.site_contact import get_site_contact_kb
from src.services.site_contact import ContactRateLimit, SiteContact

logger = logging.getLogger("webhooks.site")

router = APIRouter()

rate_limit = ContactRateLimit()


def _check_token(request: Request) -> None:
    authorization = request.headers.get("Authorization") or ""
    # An empty token closes the endpoint: "Bearer " must not match an unset secret.
    if not settings.site_contact_token or not secrets.compare_digest(
        authorization, f"Bearer {settings.site_contact_token}"
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


@router.post("/contact", status_code=status.HTTP_202_ACCEPTED)
async def site_contact(request: Request, body: SiteContact) -> dict[str, bool]:
    """zebaro.dev's contact form, posted from the site container inside the compose network.

    The Telegram message is sent inside the request, not in the background: the site shows
    "sent" only on 2xx, so a message Telegram refused must come back as 503.
    """
    # The site talks to us inside the compose network. A request that came through the
    # public tunnel carries Cloudflare's header — this endpoint does not exist for it.
    if request.headers.get("Cf-Connecting-Ip"):
        raise HTTPException(status_code=404)
    _check_token(request)
    if not rate_limit.allow(body.sender, time.monotonic()):
        raise HTTPException(status_code=429, detail="Too many messages")

    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot is not ready")
    try:
        await bot.send_message(
            chat_id=settings.telegram_admin_id,
            text=site_contact_to_html(body),
            reply_markup=get_site_contact_kb(body.reply),
            disable_web_page_preview=True,
        )
    except Exception:
        # Never the message itself in logs — only that it failed and for whom (a hash).
        logger.exception("Site contact from %s was not delivered", body.sender)
        raise HTTPException(status_code=503, detail="Telegram refused the message")

    logger.info("Site contact delivered: sender=%s locale=%s length=%d", body.sender, body.locale, len(body.message))
    return {"ok": True}
