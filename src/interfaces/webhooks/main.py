import logging

import uvicorn
from fastapi import FastAPI

from src.config import settings
from src.interfaces.webhooks.routes.endpoints import router
from src.interfaces.webhooks.routes.jobs import router as jobs_router
from src.interfaces.webhooks.routes.site import router as site_router

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
# Not under /webhook: the vacancy buttons already sent to Telegram link to {webhook_url}/jobs/r/<id>.
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
# zebaro.dev's contact form, from the site container inside the compose network only.
app.include_router(site_router, prefix="/site", tags=["site"])


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness for `scripts/prod.bat health` and post-deploy checks: the web server answers."""
    return {"status": "ok", "version": settings.version}


async def start_webhooks() -> None:
    logger.info("Starting webhook server on :8000")
    config = uvicorn.Config(app, host="0.0.0.0", log_config=None)  # nosec
    server = uvicorn.Server(config)
    await server.serve()
