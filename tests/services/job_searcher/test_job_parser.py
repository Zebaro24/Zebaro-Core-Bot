import json
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote

import pytest

from src.services.job_searcher.container import Job, JobStorage
from src.services.job_searcher.parser import _LISTENERS, JobParser, _is_challenge, browser_endpoint


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
    # The list is taken only after its cards rendered.
    mock_page.wait_for_selector.assert_awaited_once()


def _mock_browser(mocker, pages: dict[str, str]):
    mock_sm = mocker.MagicMock()
    mock_sm.check_infra_health = mocker.AsyncMock(return_value=True)
    mocker.patch("src.core.service_manager.ServiceManager.get_instance", return_value=mock_sm)

    current: dict[str, str] = {}

    async def goto(url, **_kwargs):
        if url not in pages:
            raise RuntimeError("net::ERR_CONNECTION_RESET")
        current["url"] = url

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=goto)
    mock_page.content = AsyncMock(side_effect=lambda: pages[current["url"]])
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_pw = AsyncMock()
    mock_pw.__aenter__.return_value = mock_pw
    mock_pw.chromium.connect = AsyncMock(return_value=mock_browser)
    mocker.patch("src.services.job_searcher.parser.async_playwright", return_value=mock_pw)
    mocker.patch("src.services.job_searcher.parser.Stealth").return_value.apply_stealth_async = AsyncMock()
    return mock_page


@pytest.mark.asyncio
async def test_fetch_descriptions_replaces_snippets_with_the_full_text(mocker):
    page = _mock_browser(
        mocker,
        {
            "https://jobs.dou.ua/v/1/": (
                '<div class="b-typo vacancy-section"><p>Full text</p><ul><li>Python</li></ul></div>'
            ),
            "https://jobs.dou.ua/v/3/": '<div class="b-typo vacancy-section"><p>x</p></div>',
        },
    )
    full = Job(platform_name="Dou", link="https://jobs.dou.ua/v/1/", description="Short")
    broken = Job(platform_name="Dou", link="https://jobs.dou.ua/v/2/", description="Kept")
    shorter = Job(platform_name="Dou", link="https://jobs.dou.ua/v/3/", description="Longer snippet")
    no_details = Job(platform_name="Jooble", link="https://ua.jooble.org/desc/1", description="Only this")

    await JobParser([], JobStorage()).fetch_descriptions([full, broken, shorter, no_details])

    assert full.description == "Full text\n\n• Python"
    assert broken.description == "Kept"  # one failing page does not stop the batch
    assert shorter.description == "Longer snippet"  # never replaced with less
    assert no_details.description == "Only this"
    assert page.goto.await_count == 3  # no detail selector for Jooble: never opened


def test_a_card_that_does_not_parse_is_skipped_not_fatal():
    listener = MagicMock()
    listener.platform_name = "TestPlatform"
    listener.get_all_jobs.return_value = ["bad", "good"]
    listener.get_title.return_value = "Python Dev"

    def job_id(elem: str) -> str:
        if elem == "bad":
            raise ValueError("an ad card has no id")
        return "1"

    listener.get_job_id.side_effect = job_id

    jobs = JobParser._parse_list(listener, MagicMock())

    assert [job.job_id for job in jobs] == ["1"]


@pytest.mark.asyncio
async def test_a_site_whose_vacancy_pages_are_blocked_is_not_opened_again(mocker):
    challenge = "<html><head><style>" + "x" * 5000 + "</style><title>Трохи зачекайте…</title></head></html>"
    page = _mock_browser(
        mocker,
        {
            "https://www.work.ua/jobs/1": challenge,
            "https://www.work.ua/jobs/2": challenge,
            "https://jobs.dou.ua/v/1/": '<div class="b-typo vacancy-section"><p>Full text</p></div>',
        },
    )
    page.title = AsyncMock(return_value="Трохи зачекайте…")
    first = Job(platform_name="Work.ua", link="https://www.work.ua/jobs/1", description="Snippet 1")
    second = Job(platform_name="Work.ua", link="https://www.work.ua/jobs/2", description="Snippet 2")
    dou = Job(platform_name="Dou", link="https://jobs.dou.ua/v/1/", description="Short")

    await JobParser([], JobStorage()).fetch_descriptions([first, second, dou])

    assert first.description == "Snippet 1"
    assert second.description == "Snippet 2"
    assert dou.description == "Full text"  # other sites are not affected
    opened = [call.args[0] for call in page.goto.await_args_list]
    assert "https://www.work.ua/jobs/2" not in opened


def test_cloudflare_page_is_recognised_by_its_title_past_the_stylesheet():
    content = "<html><head><style>" + "x" * 5000 + "</style><title>Трохи зачекайте…</title>"
    assert _is_challenge("Трохи зачекайте…", content)
    assert not _is_challenge("Робота: python developer", "<html>vacancies</html>")


def test_browser_endpoint_asks_for_the_full_chromium(mocker):
    mocker.patch("src.services.job_searcher.parser.settings").playwright_ws_endpoint = "ws://pw:9222"

    endpoint = browser_endpoint()

    assert endpoint.startswith("ws://pw:9222?launch-options=")
    assert json.loads(unquote(endpoint.split("launch-options=")[1])) == {"channel": "chromium", "headless": True}
