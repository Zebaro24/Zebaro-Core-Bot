"""05.11.2026: what the search lost while the home PC was off, and what it should not push.

The day's run figures (once the home PC alert), LinkedIn's window since the last full pass,
the early-startup demotion and the one-off repairs of the stored vacancies.
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


# --- the day's run figures (26.11.2026: the separate home PC alert went into them) ------------


def _run(**boards: dict[str, int]) -> dict[str, dict[str, int]]:
    from src.services.job_searcher.runs import new_counts

    names = {"Work_ua": "Work.ua", "No_Fluff_Jobs": "No Fluff Jobs"}
    return {names.get(name, name): {**new_counts(), **counts} for name, counts in boards.items()}


@pytest.mark.asyncio
async def test_the_runs_of_a_day_add_up_per_board(sql_db):
    from src.services.job_searcher.runs import record_run

    morning, noon = datetime(2026, 11, 26, 9, 5), datetime(2026, 11, 26, 13, 5)
    await record_run(
        _run(Dou={"searches": 3, "cards": 60}, Work_ua={"skipped": 3}), browser_down=False, home_down=True, now=morning
    )
    await record_run(
        _run(Dou={"searches": 3, "cards": 58}, Work_ua={"searches": 3, "cards": 20}),
        browser_down=False, home_down=False, now=noon,
    )  # fmt: skip

    day = await sql_db.kv_get("job_day:2026-11-26")
    assert day is not None
    assert (day["runs"], day["home_down"], day["last_run"]) == (2, 1, "13:05")
    assert day["platforms"]["Dou"]["cards"] == 118
    assert day["platforms"]["Work.ua"] == {"searches": 3, "cards": 20, "failed": 0, "skipped": 3}


@pytest.mark.asyncio
async def test_a_lost_count_never_fails_the_run(mocker):
    from src.services.job_searcher.runs import record_run

    mocker.patch("src.db.sql.kv_get", AsyncMock(side_effect=RuntimeError("the database is down")))

    await record_run(_run(Dou={"searches": 1}), browser_down=False, home_down=False)


@pytest.mark.asyncio
async def test_the_day_tells_a_broken_board_from_a_skipped_one_and_a_quiet_one(sql_db, mocker):
    from fake_jobs import SqlJobs

    from src.services.job_searcher.runs import day_stats, record_run

    jobs = SqlJobs(sql_db, mocker)
    base = {"platform_name": "Dou", "found_at": datetime(2026, 11, 26, 11), "user_status": "pending", "title": "x"}
    rejected = [
        {**base, "_id": f"{n:024x}", "moderation": "rejected_by_filter", "filter_reason": reason}
        for n, reason in enumerate(["not a developer role", "not a developer role", "lead"])
    ]
    jobs.docs = [
        *rejected,
        {**base, "_id": f"{9:024x}", "moderation": "review"},
        {**base, "_id": f"{10:024x}", "moderation": "sent", "user_status": "duplicate"},
    ]
    await record_run(
        _run(
            Dou={"searches": 3, "cards": 60}, No_Fluff_Jobs={"searches": 2}, LinkedIn={"skipped": 2},
            Work_ua={"searches": 2, "failed": 2},
        ),
        browser_down=False, home_down=True, now=datetime(2026, 11, 26, 13, 5),
    )  # fmt: skip

    stats = await day_stats("2026-11-26")
    assert stats is not None

    assert (stats["cards"], stats["new"], stats["repeats"], stats["filtered_out"]) == (60, 4, 1, 3)
    assert stats["reasons"] == {"not a developer role": 2, "lead": 1}
    assert stats["by_tier"] == {"top": 0, "sent": 0, "review": 1}
    assert stats["broken"] == ["No Fluff Jobs"]  # loaded, not one card; Work.ua never loaded: not the parser
    assert stats["not_searched"] == ["LinkedIn"]  # waited for the PC every time: not broken
    assert await day_stats("2026-11-25") is None  # nothing recorded is not a day of zeros


@pytest.mark.asyncio
async def test_the_period_sums_the_recorded_days(sql_db):
    from src.services.job_searcher.runs import period_sources, record_run

    for day in (24, 25):
        await record_run(
            _run(Dou={"searches": 3, "cards": 50}, Work_ua={"skipped": 2}),
            browser_down=False, home_down=True, now=datetime(2026, 11, day, 12),
        )  # fmt: skip
    found = [{"platform_name": "Dou", "moderation": "rejected_by_filter", "filter_reason": "lead"}]

    sources = await period_sources(datetime(2026, 11, 19, 12), datetime(2026, 11, 26, 12), found)
    assert sources is not None

    assert sources["days_recorded"] == 2
    assert sources["platforms"][0] == {
        "platform": "Dou", "searches": 6, "cards": 100, "failed": 0, "skipped": 0,
        "new": 1, "repeats": 0, "filtered_out": 1, "surfaced": 0,
    }  # fmt: skip
    assert sources["broken"] == [] and sources["not_searched"] == ["Work.ua"]
    assert await period_sources(datetime(2026, 10, 1), datetime(2026, 10, 7), found) is None


@pytest.mark.asyncio
async def test_the_parser_counts_cards_and_failed_pages_per_board(mocker):
    from src.services.job_searcher import parser as parser_module

    job_parser = parser_module.JobParser([], MagicMock())
    mocker.patch.object(job_parser.job_storage, "add_job", return_value=True)
    mocker.patch.object(job_parser, "_get_page_content", AsyncMock(side_effect=["<html></html>", RuntimeError("x")]))
    mocker.patch.object(job_parser, "_parse_list", return_value=_cards(0, 7))

    await job_parser._parse_search_page(MagicMock(), LinkedInListeners(), "u", "u", "")
    await job_parser._parse_search_page(MagicMock(), LinkedInListeners(), "u", "u", "")

    assert job_parser.counts["LinkedIn"]["cards"] == 7 and job_parser.counts["LinkedIn"]["failed"] == 1
