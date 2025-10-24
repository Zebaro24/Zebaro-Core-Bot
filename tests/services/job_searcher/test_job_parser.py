from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.job_searcher.job_container import JobStorage
from app.services.job_searcher.job_parser import JobParser, listeners_dict


@pytest.mark.asyncio
async def test_get_listeners_returns_correct_listener():
    for netloc, listener in listeners_dict.items():
        parser_listener = JobParser.get_listeners(netloc)
        assert parser_listener == listener

    with pytest.raises(ValueError):
        JobParser.get_listeners("unknown.site")


@pytest.mark.asyncio
async def test_parse_urls_adds_jobs(mocker):
    storage = JobStorage()

    # Page
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html></html>")

    # Context
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    # Browser
    mock_browser = AsyncMock()
    mock_browser.contexts = [mock_context]
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    # async_playwright
    mock_pw = AsyncMock()
    mock_pw.__aenter__.return_value = mock_pw
    mock_pw.__aexit__.return_value = None
    mock_pw.chromium.connect = AsyncMock(return_value=mock_browser)
    mocker.patch("app.services.job_searcher.job_parser.async_playwright", return_value=mock_pw)

    # Stealth
    mock_stealth = mocker.patch("app.services.job_searcher.job_parser.Stealth")
    mock_stealth.return_value.apply_stealth_async = AsyncMock()

    # Listener
    mock_listener = MagicMock()
    mock_listener.platform_name = "TestPlatform"
    mock_listener.get_all_jobs.return_value = ["job_elem"]
    mock_listener.get_job_id.return_value = "id123"
    mock_listener.get_title.return_value = "Python Dev"
    mock_listener.get_company.return_value = "TestCo"
    mock_listener.get_description.return_value = "desc"
    mock_listener.get_date.return_value = "2025-10-24"
    mock_listener.get_link.return_value = "https://test.com"
    mocker.patch.dict("app.services.job_searcher.job_parser.listeners_dict", {"test.site": mock_listener})

    parser = JobParser(["https://test.site"], storage)
    await parser.parse_urls()

    assert len(storage.jobs) == 1
    job = storage.jobs[0]
    assert job.title == "Python Dev"
    assert job.company == "TestCo"
    assert job.platform_name == "TestPlatform"
