from fastapi import APIRouter

from app.webhooks.routes.github import router as github_router
from app.webhooks.routes.telegram import router as telegram_router

router = APIRouter()


router.include_router(github_router, prefix="/github")
router.include_router(telegram_router, prefix="/telegram")
