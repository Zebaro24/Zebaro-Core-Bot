"""The GitHub App's webhook: every repo of the account posts here. Public, so the signature is the gate.

HMAC-SHA256 of the raw body with GH_WEBHOOK_SECRET, compared in constant time, before the body is parsed;
no secret set → every request is refused. The answer is immediate; the event is handled in the
background by the GitHub service.
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response

from src.config import settings
from src.core.service_manager import ServiceManager

logger = logging.getLogger("webhooks.github")

router = APIRouter()

MAX_BODY = 5 * 1024 * 1024  # GitHub caps payloads at 25 MB; nothing the bot reads comes near this


def signature_ok(body: bytes, signature: str) -> bool:
    secret = settings.gh_webhook_secret
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    # Bytes: compare_digest on str refuses non-ASCII, and an odd header must be a 401, not a 500.
    return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace"))


@router.post("")
async def github_webhook(request: Request) -> Response:
    declared = request.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Payload too large")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not signature_ok(body, request.headers.get("X-Hub-Signature-256", "")):
        logger.warning("GitHub webhook with a missing or wrong signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    sm = ServiceManager.get_instance()
    service = sm.all_services.get("github")
    if service is None or not sm.is_service_enabled("github") or not getattr(service, "ready", False):
        raise HTTPException(status_code=503, detail="GitHub service is disabled")

    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body is not an object")
    service.receive(delivery, event, payload)  # type: ignore[attr-defined]
    logger.info("GitHub %s for %s", event, (payload.get("repository") or {}).get("full_name", "the account"))
    return Response(status_code=200)
