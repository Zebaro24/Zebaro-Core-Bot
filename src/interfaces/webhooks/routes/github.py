import logging

from fastapi import APIRouter, HTTPException, Request, Response

from src.services.github.manager import GithubManager

logger = logging.getLogger("webhooks.github")

router = APIRouter()


@router.post("")
async def github_webhook(request: Request) -> Response:
    from src.core.service_manager import ServiceManager

    if not ServiceManager.get_instance().is_service_enabled("github"):
        raise HTTPException(status_code=503, detail="GitHub service is disabled")

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not signature:
        logger.warning("GitHub webhook request missing signature")
        raise HTTPException(status_code=401, detail="Missing signature")

    if not GithubManager.verify_signature(body, signature):
        logger.warning("GitHub webhook invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    github_manager: GithubManager | None = getattr(request.app.state, "github_manager", None)
    if github_manager is None:
        logger.error("GithubManager not initialized in app.state")
        raise HTTPException(status_code=503, detail="GitHub manager not ready")

    payload = await request.json()
    event = request.headers.get("X-GitHub-Event", "unknown")
    full_repo_name = payload.get("repository", {}).get("full_name", "unknown")

    logger.info("GitHub event: %s for repo %s", event, full_repo_name)
    await github_manager.handle(full_repo_name, event, payload)

    return Response(status_code=200)
