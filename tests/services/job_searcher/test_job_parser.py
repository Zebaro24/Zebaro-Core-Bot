from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.job_searcher.container import JobStorage
from src.services.job_searcher.parser import _LISTENERS, JobParser


@pytest.mark.asyncio
async def test_get_listeners_returns_correct_listener():
    for netloc, listener in _LISTENERS.items():
        parser_listener = JobParser.get_listeners(netloc)
        assert parser_listener == listener

    with pytest.raises(ValueError):
        JobParser.get_listeners("unknown.site")


@pytest.mark.asyncio
async def test_parse_urls_adds_jobs(mocker):
    storage = JobStorage()

    mock_sm = mocker.MagicMock()
    mock_sm.check_infra_health = mocker.AsyncMock(return_value=True)
    mocker.patch("src.core.service_manager.ServiceManager.get_instance", return_value=mock_sm)

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html></html>")

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.__aenter__.return_value = mock_pw
    mock_pw.__aexit__.return_value = None
    mock_pw.chromium.connect = AsyncMock(return_value=mock_browser)
    mocker.patch("src.services.job_searcher.parser.async_playwright", return_value=mock_pw)

    mock_stealth = mocker.patch("src.services.job_searcher.parser.Stealth")
    mock_stealth.return_value.apply_stealth_async = AsyncMock()

    mock_listener = MagicMock()
    mock_listener.platform_name = "TestPlatform"
    mock_listener.get_all_jobs.return_value = ["job_elem"]
    mock_listener.get_job_id.return_value = "id123"
    mock_listener.get_title.return_value = "Python Dev"
    mock_listener.get_company.return_value = "TestCo"
    mock_listener.get_description.return_value = "desc"
    mock_listener.get_date.return_value = "2025-10-24"
    mock_listener.get_link.return_value = "https://test.com"
    mocker.patch.dict("src.services.job_searcher.parser._LISTENERS", {"test.site": mock_listener})

    parser = JobParser(["https://test.site"], storage)
    await parser.parse_urls()

    assert len(storage.jobs) == 1
    job = storage.jobs[0]
    assert job.title == "Python Dev"
    assert job.company == "TestCo"
    assert job.platform_name == "TestPlatform"
