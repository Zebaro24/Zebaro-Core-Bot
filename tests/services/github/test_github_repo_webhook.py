import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.personal_github_token = "fake_token"
mock_settings.personal_github_secret = "fake_secret"
sys.modules["src.config"] = MagicMock(settings=mock_settings)

from src.services.github.webhook import GithubRepoWebhook  # noqa: E402


@pytest.fixture
def webhook_instance(mocker):
    mocker.patch("src.services.github.webhook.settings", mock_settings)
    return GithubRepoWebhook(full_repo_name="user/repo", github_webhook_url="https://example.com/webhook")


def _make_mock_client(get_response_json, post_status=201, patch_status=200, delete_status=204):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=MagicMock(json=MagicMock(return_value=get_response_json)))
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=post_status, text=""))
    mock_client.patch = AsyncMock(return_value=MagicMock(status_code=patch_status, text=""))
    mock_client.delete = AsyncMock(return_value=MagicMock(status_code=delete_status, text=""))
    return mock_client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "existing_webhooks,expected_post_called,expected_patch_called",
    [
        ([], True, False),
        (
            [
                {
                    "id": 123,
                    "config": {
                        "url": "https://example.com/webhook",
                        "content_type": "form",
                        "secret": "old_secret",
                    },
                    "events": ["push"],
                }
            ],
            False,
            True,
        ),
        (
            [
                {
                    "id": 123,
                    "config": {
                        "url": "https://example.com/webhook",
                        "content_type": "json",
                        "secret": "fake_secret",
                    },
                    "events": ["push", "pull_request", "workflow_run"],
                }
            ],
            False,
            False,
        ),
    ],
)
async def test_enable_webhook(mocker, webhook_instance, existing_webhooks, expected_post_called, expected_patch_called):
    mock_client = _make_mock_client(existing_webhooks)
    mocker.patch("src.services.github.webhook.httpx.AsyncClient", return_value=mock_client)

    await webhook_instance.enable_webhook()

    if expected_post_called:
        mock_client.post.assert_called_once()
    else:
        mock_client.post.assert_not_called()

    if expected_patch_called:
        mock_client.patch.assert_called_once()
    else:
        mock_client.patch.assert_not_called()

    mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_disable_webhook(mocker, webhook_instance):
    existing = [{"id": 123, "config": {"url": webhook_instance.github_webhook_url}}]
    mock_client = _make_mock_client(existing)
    mocker.patch("src.services.github.webhook.httpx.AsyncClient", return_value=mock_client)

    await webhook_instance.disable_webhook()

    mock_client.delete.assert_called_once()
