import sys
from unittest.mock import AsyncMock, MagicMock

from starlette.routing import Route

mock_settings = MagicMock()
mock_settings.app_name = "test"
mock_settings.description = ""
mock_settings.version = "0.0.0"
mock_settings.debug = False

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.webhooks.main import app  # noqa: E402


def test_vacancy_redirect_lives_where_the_telegram_buttons_point():
    paths = {route.path for route in app.routes if isinstance(route, Route)}
    assert "/jobs/r/{job_id}" in paths
    assert "/webhook/telegram" in paths


def test_health_is_public_and_reports_the_version():
    paths = {route.path for route in app.routes if isinstance(route, Route)}
    assert "/health" in paths


def test_site_contact_lives_where_the_site_posts():
    # zebaro.dev's CONTACT_ENDPOINT is http://zebaro-core-bot:8000/site/contact.
    paths = {route.path for route in app.routes if isinstance(route, Route)}
    assert "/site/contact" in paths
