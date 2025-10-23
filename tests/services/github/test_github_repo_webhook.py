import sys
from unittest.mock import MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.personal_github_token = "fake_token"
mock_settings.personal_github_secret = "fake_secret"
sys.modules["app.config"] = MagicMock(settings=mock_settings)

from app.services.github.github_repo_webhook import GithubRepoWebhook  # noqa: E402


@pytest.fixture
def webhook_instance():
    return GithubRepoWebhook(full_repo_name="user/repo", github_webhook_url="https://example.com/webhook")


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
def test_enable_webhook(mocker, webhook_instance, existing_webhooks, expected_post_called, expected_patch_called):
    mock_get = mocker.patch("app.services.github.github_repo_webhook.requests.get")
    mock_post = mocker.patch("app.services.github.github_repo_webhook.requests.post")
    mock_patch = mocker.patch("app.services.github.github_repo_webhook.requests.patch")
    mock_delete = mocker.patch("app.services.github.github_repo_webhook.requests.delete")

    mock_get.return_value.json.return_value = existing_webhooks
    mock_post.return_value.status_code = 201
    mock_patch.return_value.status_code = 200
    mock_delete.return_value.status_code = 204

    webhook_instance.enable_webhook()

    if expected_post_called:
        mock_post.assert_called_once()
    else:
        mock_post.assert_not_called()

    if expected_patch_called:
        mock_patch.assert_called_once()
    else:
        mock_patch.assert_not_called()

    mock_delete.assert_not_called()


def test_disable_webhook(mocker, webhook_instance):
    mock_get = mocker.patch("app.services.github.github_repo_webhook.requests.get")
    mock_delete = mocker.patch("app.services.github.github_repo_webhook.requests.delete")

    mock_get.return_value.json.return_value = [{"id": 123, "config": {"url": webhook_instance.github_webhook_url}}]
    mock_delete.return_value.status_code = 204

    webhook_instance.disable_webhook()

    mock_delete.assert_called_once()
