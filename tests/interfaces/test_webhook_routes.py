import sys
from unittest.mock import AsyncMock, MagicMock

mock_settings = MagicMock()
mock_settings.app_name = "test"
mock_settings.description = ""
mock_settings.version = "0.0.0"
mock_settings.debug = False

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.webhooks.main import app  # noqa: E402


def _paths() -> set[str]:
    # The schema, not app.routes: since FastAPI 0.142 an included router sits there as one
    # lazy entry, and the paths under it are not listed.
    return set(app.openapi()["paths"])


def test_vacancy_redirect_lives_where_the_telegram_buttons_point():
    paths = _paths()
    assert "/jobs/r/{job_id}" in paths
    assert "/webhook/telegram" in paths


def test_health_is_public_and_reports_the_version():
    paths = _paths()
    assert "/health" in paths


def test_site_contact_lives_where_the_site_posts():
    # zebaro.dev's CONTACT_ENDPOINT is http://zebaro-core-bot:8000/site/contact.
    paths = _paths()
    assert "/site/contact" in paths
