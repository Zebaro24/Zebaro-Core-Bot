import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.interfaces.webhooks.routes import telegram
from src.interfaces.webhooks.routes.telegram import telegram_webhook


def _request(dp):
    request = MagicMock()
    request.app.state.bot = MagicMock()
    request.app.state.dp = dp
    request.json = AsyncMock(return_value={"update_id": 213469186})
    return request


@pytest.mark.asyncio
async def test_telegram_webhook_answers_before_the_handler_finishes():
    release = asyncio.Event()

    async def slow_handler(*_):
        await release.wait()

    dp = MagicMock()
    dp.feed_update = AsyncMock(side_effect=slow_handler)

    response = await telegram_webhook(_request(dp))

    assert response.status_code == 200
    assert len(telegram._update_tasks) == 1
    release.set()
    await asyncio.gather(*telegram._update_tasks)
    await asyncio.sleep(0)
    assert not telegram._update_tasks


@pytest.mark.asyncio
async def test_telegram_webhook_logs_a_failing_handler_instead_of_raising(caplog):
    dp = MagicMock()
    dp.feed_update = AsyncMock(side_effect=RuntimeError("Playwright version mismatch"))

    with caplog.at_level(logging.ERROR, logger="webhooks.telegram"):
        response = await telegram_webhook(_request(dp))
        await asyncio.gather(*telegram._update_tasks)

    assert response.status_code == 200
    assert "update id=213469186" in caplog.text
