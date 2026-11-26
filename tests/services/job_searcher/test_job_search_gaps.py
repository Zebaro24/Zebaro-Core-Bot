"""05.11.2026: what the search lost while the home PC was off, and what it should not push.

The home PC alert, LinkedIn's window since the last full pass, the early-startup demotion and
the one-off repairs of the stored vacancies.
"""

import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Before any src import: the real settings read the developer's .env (CLAUDE.md, tests).
sys.modules.setdefault("src.config", MagicMock(settings=MagicMock()))

from src.services.job_searcher.container import Job  # noqa: E402
from src.services.job_searcher.filter import REVIEW, SENT, TOP, WARN_EARLY_STARTUP, evaluate  # noqa: E402
from src.services.job_searcher.listeners.linkedin import LinkedInListeners  # noqa: E402
from src.services.job_searcher.search_window import (  # noqa: E402
    MAX_PAGES,
    MAX_WINDOW_S,
    MIN_WINDOW_S,
    pages_for,
    window_since,
)

_TEXT = (
    "We build a B2B platform. Stack: Python, FastAPI, PostgreSQL on the back, React and Next.js on "
    "the front. 2 years of commercial experience. You will design APIs, ship features end to end "
    "and work closely with the product team on what users need next."
)


def _job(title: str = "Middle Full-Stack Developer (Python / React)", extra: str = "") -> Job:
    return Job(platform_name="Djinni", title=title, company="Acme", description=f"{_TEXT} {extra}".strip(),
               work_format="remote", required_years=2)  # fmt: skip


# --- early startup ------------------------------------------------------------------------


def test_a_full_stack_match_is_top_without_startup_words():
    assert evaluate(_job()).moderation == TOP


@pytest.mark.parametrize(
    "title,extra",
    [
        ("Founding Full-Stack Engineer (Python / React)", ""),
        ("Middle Full-Stack Developer (Python / React)", "We are a pre-seed startup of four people."),
        ("Middle Full-Stack Developer (Python / React)", "Join us as the first engineer."),
        ("Middle Full-Stack Developer (Python / React)", "We are an early-stage company in stealth mode."),
        ("Middle Full-Stack Developer (Python / React)", "Стартап на ранній стадії, команда з п'яти людей."),
    ],
)
def test_an_early_startup_goes_down_to_review_and_is_never_rejected(title, extra):
    verdict = evaluate(_job(title, extra))

    assert verdict.moderation == REVIEW
    assert WARN_EARLY_STARTUP in verdict.warnings


def test_plain_startup_is_not_an_early_startup():
    # Outsourcers write "we work with startups": as many applications there as anywhere.
    verdict = evaluate(_job(extra="We help startups and enterprises build their products."))

    assert verdict.moderation in (TOP, SENT)
    assert WARN_EARLY_STARTUP not in verdict.warnings


# --- LinkedIn's window ---------------------------------------------------------------------

_SEARCH = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords=python&location=Ukraine&f_WT=2&f_TPR=r86400&sortBy=DD"
)


def test_the_window_reaches_back_to_the_last_full_pass_between_a_day_and_a_week():
    now = datetime(2026, 11, 5, 12)

    assert window_since(None, now) == MIN_WINDOW_S
    assert window_since(now - timedelta(hours=1), now) == MIN_WINDOW_S
    assert window_since(now - timedelta(days=3), now) == 3 * 24 * 3600 + 3600
    assert window_since(now - timedelta(days=30), now) == MAX_WINDOW_S


def test_only_a_window_over_a_day_pages_on():
    assert pages_for(MIN_WINDOW_S) == 1
    assert pages_for(MIN_WINDOW_S + 1) == MAX_PAGES


def test_linkedin_search_url_sets_the_window_and_the_page():
    listeners = LinkedInListeners()

    assert listeners.search_url(_SEARCH, 86400, 0) == _SEARCH
    assert listeners.search_url(_SEARCH, 270000, 0) == _SEARCH.replace("f_TPR=r86400", "f_TPR=r270000")
    assert listeners.search_url(_SEARCH, 270000, 2).endswith("f_TPR=r270000&sortBy=DD&start=20")


async def _paged(mocker, pages: list[list[Job]], known: list[int]) -> tuple[int, list[str]]:
    from src.services.job_searcher import parser as parser_module

    asked: list[str] = []

    async def page(_page, _listeners, page_url, _search, _via, _first=True):
        asked.append(page_url)
        return pages[len(asked) - 1]

    job_parser = parser_module.JobParser([], MagicMock())
    mocker.patch.object(job_parser, "_parse_search_page", side_effect=page)
    mocker.patch.object(parser_module, "known_count", AsyncMock(side_effect=known))
    found = await job_parser._parse_windowed(MagicMock(), LinkedInListeners(), _SEARCH, 3 * 86400, "")
    return found, asked


def _cards(start: int, count: int = 10) -> list[Job]:
    return [Job(platform_name="LinkedIn", job_id=str(start + n)) for n in range(count)]


@pytest.mark.asyncio
async def test_a_wide_window_pages_until_a_page_brings_nothing_new(mocker):
    found, asked = await _paged(mocker, [_cards(0), _cards(10), _cards(20)], known=[3, 10])

    assert found == 20
    assert [url.rsplit("start=", 1)[-1] if "start=" in url else "0" for url in asked] == ["0", "10"]


@pytest.mark.asyncio
async def test_a_short_page_is_the_last_one(mocker):
    found, asked = await _paged(mocker, [_cards(0, 4)], known=[0])

    assert (found, len(asked)) == (4, 1)


# --- home PC alert -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_alert_before_noon(sql_db):
    from src.services.job_searcher.home import ALERT_STATE_ID, home_alert_due

    assert not await home_alert_due(datetime(2026, 11, 5, 11, 59))
    assert await sql_db.kv_get(ALERT_STATE_ID) is None  # nothing claimed


@pytest.mark.asyncio
async def test_alert_once_a_day_from_noon(sql_db):
    from src.services.job_searcher.home import home_alert_due

    assert await home_alert_due(datetime(2026, 11, 5, 12, 0))
    assert not await home_alert_due(datetime(2026, 11, 5, 15, 0))  # the day is claimed
    assert await home_alert_due(datetime(2026, 11, 6, 12, 0))


@pytest.mark.asyncio
async def test_an_alert_the_db_cannot_claim_is_not_sent(mocker):
    from src.services.job_searcher import home

    mocker.patch("src.db.sql.kv_claim", AsyncMock(side_effect=RuntimeError("the database is down")))

    assert not await home.home_alert_due(datetime(2026, 11, 5, 12, 0))


def test_home_down_message_names_the_skipped_boards():
    from src.interfaces.tg.formatters.job import home_down_html

    text = home_down_html(["Robota.ua", "Work.ua", "LinkedIn"])

    assert "Robota.ua, Work.ua, LinkedIn" in text
    assert "До завтра" in text
