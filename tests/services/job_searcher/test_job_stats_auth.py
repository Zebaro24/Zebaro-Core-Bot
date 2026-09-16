import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

mock_settings = MagicMock()
mock_settings.telegram_docker_access_ids = [123]
mock_settings.job_stats_api_token = "secret-token"

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from fastapi import HTTPException  # noqa: E402

from src.interfaces.webhooks.routes.jobs import _check_token  # noqa: E402


def _request_with_auth_header(value: str | None):
    request = MagicMock()
    request.headers.get.return_value = value
    return request


def test_check_token_accepts_correct_bearer_token(mocker):
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", mock_settings)
    _check_token(_request_with_auth_header("Bearer secret-token"))


def test_check_token_rejects_wrong_token(mocker):
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", mock_settings)
    with pytest.raises(HTTPException) as exc_info:
        _check_token(_request_with_auth_header("Bearer wrong-token"))
    assert exc_info.value.status_code == 401


def test_check_token_rejects_missing_header(mocker):
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", mock_settings)
    with pytest.raises(HTTPException):
        _check_token(_request_with_auth_header(None))


def test_check_token_rejects_empty_bearer_when_token_not_configured(mocker):
    unconfigured_settings = MagicMock()
    unconfigured_settings.job_stats_api_token = ""
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", unconfigured_settings)

    with pytest.raises(HTTPException) as exc_info:
        _check_token(_request_with_auth_header("Bearer "))
    assert exc_info.value.status_code == 401
