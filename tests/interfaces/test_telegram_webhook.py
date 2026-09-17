from unittest.mock import AsyncMock, MagicMock

import pytest

from src.interfaces.webhooks.routes.telegram import telegram_webhook


def _request(dp):
    request = MagicMock()
    request.app.state.bot = MagicMock()
    request.app.state.dp = dp
    request.json = AsyncMock(return_value={"update_id": 213469186})
    return request


@pytest.mark.asyncio
async def test_telegram_webhook_returns_200_when_handler_fails():
    dp = MagicMock()
    dp.feed_update = AsyncMock(side_effect=RuntimeError("Playwright version mismatch"))

    response = await telegram_webhook(_request(dp))

    assert response.status_code == 200
    dp.feed_update.assert_awaited_once()
