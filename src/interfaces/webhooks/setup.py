from aiogram import Bot, Dispatcher

from src.config import settings


def get_url_webhook_telegram() -> str:
    return f"{settings.webhook_url}/webhook/telegram"


def setup_telegram_webhook(bot: Bot, dp: Dispatcher) -> None:
    """Inject bot and dispatcher into FastAPI app.state.

    Called from tg/main.py before the webhook is activated on Telegram's side.
    """
    from src.interfaces.webhooks.main import app

    app.state.bot = bot
    app.state.dp = dp
