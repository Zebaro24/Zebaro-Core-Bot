from app.config import settings
from app.webhooks.routes import telegram
from aiogram import Bot, Dispatcher


def get_url_webhook_github():
    return f"{settings.webhook_url}/webhook/github"


def get_url_webhook_telegram():
    return f"{settings.webhook_url}/webhook/telegram"


def setup_webhook_telegram(bot: Bot, dp: Dispatcher):
    telegram.bot = bot
    telegram.dp = dp


if __name__ == '__main__':
    print(get_url_webhook_telegram())
    print(get_url_webhook_github())
