import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.personal_github_token = "fake_token"
mock_settings.personal_github_secret = "fake_secret"

fake_db_client: Any = types.ModuleType("app.db.client")
fake_db_client.github_notification_collection = MagicMock()

sys.modules["app.db.client"] = fake_db_client
sys.modules["app.config"] = MagicMock(settings=mock_settings)

from app.services.github.github_manager import GithubManager  # noqa: E402


@pytest.fixture
def mock_bot(mocker):
    bot = mocker.MagicMock()
    bot.send_message = mocker.AsyncMock()
    bot.edit_message_text = mocker.AsyncMock()
    return bot


@pytest.fixture
def github_manager(mock_bot, mocker):
    mocker.patch("app.services.github.github_manager.GithubRepoWebhook", autospec=True)
    mocker.patch("app.services.github.github_manager.GithubRepoEvent", autospec=True)

    return GithubManager(bot=mock_bot, github_webhook_url="https://example.com/webhook")


def test_verify_signature(github_manager):
    body = b"test payload"
    import hashlib
    import hmac

    mac = hmac.new(mock_settings.personal_github_secret.encode(), msg=body, digestmod=hashlib.sha256)
    signature = "sha256=" + mac.hexdigest()

    assert github_manager.verify_signature(body, signature) is True
    assert github_manager.verify_signature(body, "wrong_signature") is False


@pytest.mark.asyncio
async def test_handle_calls_event(mocker, github_manager):
    handle_mock: AsyncMock = mocker.AsyncMock()
    event = mocker.MagicMock()
    event.handle = handle_mock
    GithubManager.github_repo_events["user/repo"] = event

    payload = {"key": "value"}
    await GithubManager.handle("user/repo", "push", payload)

    handle_mock.assert_called_once_with("push", payload)


@pytest.mark.asyncio
async def test_handle_logs_warning_for_unknown_event(caplog):
    caplog.set_level("WARNING")
    GithubManager.github_repo_events.clear()
    await GithubManager.handle("unknown/repo", "push", {})
    assert "Event for unknown/repo not found" in caplog.text


def test_create_handler_creates_webhook_and_event(mocker, github_manager):
    module = sys.modules["app.services.github.github_manager"]
    webhook_cls = mocker.patch.object(module, "GithubRepoWebhook")
    event_cls = mocker.patch.object(module, "GithubRepoEvent")

    github_manager.create_handler("user/repo", tg_chat_id=12345)

    webhook_cls.assert_called_once_with("user/repo", github_manager.github_webhook_url)
    webhook_cls.return_value.enable_webhook.assert_called_once()
    event_cls.assert_called_once_with("user/repo", github_manager.bot, 12345, None)


def test_delete_handler_disables_and_removes(mocker, github_manager):
    github_manager.create_handler("user/repo", tg_chat_id=12345)

    webhook_mock = github_manager.github_repo_webhooks["user/repo"]
    delete_handler_mock = mocker.patch.object(webhook_mock, "disable_webhook")

    github_manager.delete_handler("user/repo")

    delete_handler_mock.assert_called_once()
    assert "user/repo" not in github_manager.github_repo_webhooks
    assert "user/repo" not in github_manager.github_repo_events


def test_delete_handler_logs_warning_for_unknown(caplog, github_manager):
    caplog.set_level("WARNING")
    github_manager.delete_handler("unknown/repo")
    assert "Webhook for unknown/repo not found" in caplog.text


def test_get_webhook_returns_correct_object(github_manager):
    github_manager.create_handler("user/repo", tg_chat_id=12345)
    webhook = github_manager.get_webhook("user/repo")
    assert webhook is github_manager.github_repo_webhooks["user/repo"]


def test_get_event_returns_correct_object(github_manager):
    github_manager.create_handler("user/repo", tg_chat_id=12345)
    event = github_manager.get_event("user/repo")
    assert event is github_manager.github_repo_events["user/repo"]


@pytest.mark.asyncio
async def test_add_notification_to_db_inserts_if_not_exists(mocker):
    mock_collection = mocker.patch("app.services.github.github_manager.github_notification_collection")
    mock_collection.find_one = mocker.AsyncMock(return_value=None)
    mock_collection.insert_one = mocker.AsyncMock()
    manager_cls = GithubManager

    await manager_cls.add_notification_to_db("user/repo", 12345, thread_id=1)
    mock_collection.insert_one.assert_called_once_with(
        {"full_repo_name": "user/repo", "tg_chat_id": 12345, "thread_id": 1}
    )


@pytest.mark.asyncio
async def test_add_notification_to_db_does_not_insert_if_exists(mocker):
    mock_collection = mocker.patch("app.services.github.github_manager.github_notification_collection")
    mock_collection.find_one = mocker.AsyncMock(return_value={"full_repo_name": "user/repo"})
    mock_collection.insert_one = mocker.AsyncMock()
    manager_cls = GithubManager

    await manager_cls.add_notification_to_db("user/repo", 12345, thread_id=1)
    mock_collection.insert_one.assert_not_called()
