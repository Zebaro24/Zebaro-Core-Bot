from fastapi import APIRouter

from src.interfaces.webhooks.routes.github import router as github_router
from src.interfaces.webhooks.routes.telegram import router as telegram_router

router = APIRouter()

router.include_router(github_router, prefix="/github")
router.include_router(telegram_router, prefix="/telegram")
