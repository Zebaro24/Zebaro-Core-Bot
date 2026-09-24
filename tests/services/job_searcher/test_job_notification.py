import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]
mock_settings.webhook_url = "https://test.zebaro.dev"

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.tg.notification import job_notification as notification  # noqa: E402
from src.interfaces.tg.notification.job_notification import _get_reply_markup  # noqa: E402
from src.services.job_searcher.container import Job  # noqa: E402


def test_get_reply_markup_uses_action_kb_when_job_id_present():
    markup = _get_reply_markup(Job(platform_name="Dou", link="https://example.com/job"), "mongo_id_123")
    assert markup is not None

    urls = [button.url for row in markup.inline_keyboard for button in row if button.url]
    assert any("/jobs/r/mongo_id_123" in url for url in urls)
    callback_actions = [
        button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data
    ]
    assert len(callback_actions) == 2
    styles = {button.text: button.style for row in markup.inline_keyboard for button in row}
    assert styles == {"🔗 Вакансия": "primary", "✅ Откликнулся": "success", "❌ Не интересует": "danger"}


def test_get_reply_markup_falls_back_to_raw_link_when_job_id_missing():
    markup = _get_reply_markup(Job(link="https://example.com/job"), None)
    assert markup is not None

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].url == "https://example.com/job"


def test_get_reply_markup_returns_none_when_nothing_available():
    assert _get_reply_markup(Job(), None) is None


def test_copies_get_their_own_link_buttons_and_djinni_the_block_button():
    job = Job(platform_name="Djinni", copies=[{"platform": "Work.ua", "id": "copy_1"}])
    markup = _get_reply_markup(job, "mongo_id_1")
    assert markup is not None

    texts = [button.text for row in markup.inline_keyboard for button in row]
    assert texts == ["🔗 Вакансия", "🔗 Work.ua", "✅ Откликнулся", "❌ Не интересует", "⛔ Djinni не пускает"]
    urls = [button.url for row in markup.inline_keyboard for button in row if button.url]
    assert urls[1].endswith("/jobs/r/copy_1")  # clicks on a copy are tracked too

    dou = _get_reply_markup(Job(platform_name="Dou"), "mongo_id_2")
    assert dou is not None
    assert all("не пускает" not in button.text for row in dou.inline_keyboard for button in row)


def _job(moderation="sent"):
    return Job(title="Full Stack Developer", platform_name="Dou", company="Acme", moderation=moderation)


@pytest.mark.asyncio
async def test_send_job_sends_a_rich_message_and_rings_only_for_your_stack():
    bot = MagicMock()
    bot.send_rich_message = AsyncMock()

    assert await notification._send_job(bot, _job("sent"), None) is True
    assert await notification._send_job(bot, _job("review"), None) is True

    first, second = bot.send_rich_message.await_args_list
    assert "<h3>🔥 Full Stack Developer</h3>" in first.kwargs["rich_message"].html
    assert first.kwargs["disable_notification"] is False
    assert second.kwargs["disable_notification"] is True


@pytest.mark.asyncio
async def test_send_job_falls_back_to_plain_html_when_rich_is_refused():
    bot = MagicMock()
    bot.send_rich_message = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="bad rich markup"))
    bot.send_message = AsyncMock()

    assert await notification._send_job(bot, _job(), None) is True
    assert "Full Stack Developer - Dou" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_send_job_waits_out_flood_control_and_retries(mocker):
    sleep = mocker.patch("src.interfaces.tg.notification.job_notification.asyncio.sleep", new=AsyncMock())
    bot = MagicMock()
    bot.send_rich_message = AsyncMock(
        side_effect=[TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=3), None]
    )

    assert await notification._send_job(bot, _job(), None) is True
    assert bot.send_rich_message.await_count == 2
    sleep.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_send_job_skips_a_vacancy_telegram_rejects_twice():
    bot = MagicMock()
    bot.send_rich_message = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="bad rich markup"))
    bot.send_message = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="can't parse entities"))

    assert await notification._send_job(bot, _job(), None) is False


@pytest.mark.asyncio
async def test_job_notification_skips_while_another_search_is_running(mocker):
    run = mocker.patch(
        "src.interfaces.tg.notification.job_notification._run_job_notification", new=AsyncMock(return_value=7)
    )

    async with notification._run_lock:
        assert notification.is_job_search_running()
        assert await notification.job_notification(MagicMock()) == 0
    run.assert_not_awaited()

    assert await notification.job_notification(MagicMock()) == 7
