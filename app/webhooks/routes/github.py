import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.services.github.github_manager import GithubManager

router = APIRouter()

logger = logging.getLogger("github.webhook")


@router.post("")
async def root(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if signature is None or not GithubManager.verify_signature(body, signature):
        logger.warning("Received invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event = request.headers.get("X-GitHub-Event")
    full_repo_name = payload["repository"]["full_name"]

    await GithubManager.handle(full_repo_name, event, payload)

    return Response(status_code=200)
