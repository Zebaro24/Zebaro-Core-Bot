import logging

import uvicorn
from fastapi import FastAPI

from src.config import settings
from src.interfaces.webhooks.routes.endpoints import router

logger = logging.getLogger("webhooks.main")

app = FastAPI(
    title=settings.app_name,
    description=settings.description,
    version=settings.version,
    debug=settings.debug,
)

# Route handlers access shared objects (bot, dp, github_manager) via app.state.
# These are injected by setup_telegram_webhook() before the first request arrives.
app.state.bot = None
app.state.dp = None
app.state.github_manager = None

app.include_router(router, prefix="/webhook", tags=["webhook"])


async def start_webhooks() -> None:
    logger.info("Starting webhook server on :8000")
    config = uvicorn.Config(app, host="0.0.0.0", log_config=None)  # nosec
    server = uvicorn.Server(config)
    await server.serve()
