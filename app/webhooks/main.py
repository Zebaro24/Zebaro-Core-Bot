import uvicorn
from fastapi import FastAPI

from app.config import settings
from app.webhooks.routes.endpoints import router

app = FastAPI(
    title=settings.app_name,
    description=settings.description,
    version=settings.version,
    debug=settings.debug,
)

app.include_router(router, prefix="/webhook", tags=["webhook"])


async def start_webhooks():
    config = uvicorn.Config(app, log_config=None)
    server = uvicorn.Server(config)
    await server.serve()
