"""05.11.2026: what the search lost while the home PC was off, and what it should not push.

The home PC alert, LinkedIn's window since the last full pass, the early-startup demotion and
the one-off repairs of the stored vacancies.
"""

import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

# Before any src import: the real settings read the developer's .env (CLAUDE.md, tests).
sys.modules.setdefault("src.config", MagicMock(settings=MagicMock()))
sys.modules.setdefault("src.db.client", MagicMock())

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


def _meta(modified: int = 0, upserted: object = None, error: Exception | None = None) -> MagicMock:
    meta = MagicMock()
    result = MagicMock(modified_count=modified, upserted_id=upserted)
    meta.update_one = AsyncMock(side_effect=error) if error else AsyncMock(return_value=result)
    return meta


@pytest.mark.asyncio
async def test_no_alert_before_noon(mocker):
    from src.services.job_searcher.home import home_alert_due

    meta = _meta(upserted="x")
    mocker.patch.dict(sys.modules, {"src.db.client": MagicMock(meta_collection=meta)})

    assert not await home_alert_due(datetime(2026, 11, 5, 11, 59))
    meta.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_alert_once_a_day_from_noon(mocker):
    from src.services.job_searcher.home import home_alert_due

    first = _meta(upserted="home_proxy_alert")
    mocker.patch.dict(sys.modules, {"src.db.client": MagicMock(meta_collection=first)})
    assert await home_alert_due(datetime(2026, 11, 5, 12, 0))

    # The day is claimed: the filter on alerted_on misses and the upsert hits the existing _id.
    again = _meta(error=RuntimeError("E11000 duplicate key"))
    mocker.patch.dict(sys.modules, {"src.db.client": MagicMock(meta_collection=again)})
    assert not await home_alert_due(datetime(2026, 11, 5, 15, 0))

    next_day = _meta(modified=1)
    mocker.patch.dict(sys.modules, {"src.db.client": MagicMock(meta_collection=next_day)})
    assert await home_alert_due(datetime(2026, 11, 6, 12, 0))


def test_home_down_message_names_the_skipped_boards():
    from src.interfaces.tg.formatters.job import home_down_html

    text = home_down_html(["Robota.ua", "Work.ua", "LinkedIn"])

    assert "Robota.ua, Work.ua, LinkedIn" in text
    assert "До завтра" in text


# --- repairs -------------------------------------------------------------------------------


def _stored(seconds: int, status: str | None = None, **fields) -> dict:
    moment = datetime(2026, 9, 21, 9, 46) + timedelta(seconds=seconds)
    return {"_id": ObjectId.from_datetime(moment), "platform_name": "Dou", "job_id": "370398",
            "user_status": status, **fields}  # fmt: skip


def test_same_run_copies_group_and_the_furthest_one_stays():
    from src.services.job_searcher.repair import _furthest, same_run_groups

    # YozmaTech on DOU: four copies stored in two seconds, two "applied", two "not interested".
    run = [_stored(0, "not_interested"), _stored(1, "applied"), _stored(1, "applied", click_count=2),
           _stored(2, "not_interested")]  # fmt: skip
    repost = _stored(90 * 86400)  # the same id three months later is not the same run

    groups = same_run_groups([*run, repost])

    assert [len(group) for group in groups] == [4]
    assert _furthest(groups[0]) is run[2]


def test_a_run_already_repaired_is_left_alone():
    from src.services.job_searcher.repair import same_run_groups

    assert same_run_groups([_stored(0, "applied"), _stored(1, "duplicate")]) == []


class _FakeJobs:
    """The few MongoDB operations the repairs use, over a list of dicts."""

    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs
        self.updates: list[tuple[dict, dict]] = []
        self.update_many = AsyncMock()
        self.aggregate: object = None

    @staticmethod
    def _match(doc: dict, query: dict) -> bool:
        for key, cond in query.items():
            if key == "$or":
                if not any(_FakeJobs._match(doc, part) for part in cond):
                    return False
                continue
            value = doc.get(key)
            if isinstance(cond, dict):
                if "$type" in cond and not isinstance(value, datetime):
                    return False
                if "$ne" in cond and value == cond["$ne"]:
                    return False
                if "$lt" in cond and not value < cond["$lt"]:
                    return False
            elif value != cond:
                return False
        return True

    def find(self, query: dict, _projection: dict | None = None):
        matched = [dict(doc) for doc in self.docs if self._match(doc, query)]

        async def iterate():
            for doc in matched:
                yield doc

        return iterate()

    async def update_one(self, query: dict, update: dict) -> MagicMock:
        self.updates.append((query, update))
        doc = next((doc for doc in self.docs if self._match(doc, query)), None)
        if doc is not None:
            doc.update(update.get("$set", {}))
        return MagicMock(modified_count=int(doc is not None))


@pytest.mark.asyncio
async def test_djinni_dates_shift_once_and_only_before_the_cutoff(mocker):
    from src.services.job_searcher import repair

    now = datetime(2026, 11, 5, 15)
    cutoff = ObjectId.from_datetime(now)
    old = {"_id": ObjectId.from_datetime(now - timedelta(days=30)), "platform_name": "Djinni",
           "date": datetime(2026, 10, 6, 14, 0)}  # fmt: skip
    fresh = {"_id": ObjectId.from_datetime(now + timedelta(hours=1)), "platform_name": "Djinni",
             "date": datetime(2026, 11, 5, 14, 0)}  # stored by the new parser, UTC already  # fmt: skip
    dou = {"_id": old["_id"], "platform_name": "Dou", "date": datetime(2026, 10, 6)}
    jobs = _FakeJobs([old, fresh, dou])
    meta = MagicMock()
    meta.find_one_and_update = AsyncMock(return_value={"_id": repair.REPAIR_ID, "djinni_utc_before": cutoff})
    mocker.patch.object(repair, "jobs_collection", jobs)
    mocker.patch.object(repair, "meta_collection", meta)

    assert await repair.djinni_dates_to_utc(now) == 1
    assert await repair.djinni_dates_to_utc(now + timedelta(days=1)) == 0  # a second start

    assert old["date"] == datetime(2026, 10, 6, 11, 0) and old["date_utc"] is True  # Kyiv, UTC+3
    assert fresh["date"] == datetime(2026, 11, 5, 14, 0)
    assert dou["date"] == datetime(2026, 10, 6)
    # The first cutoff is kept: $setOnInsert never moves it.
    assert all("$setOnInsert" in call.args[1] for call in meta.find_one_and_update.await_args_list)


@pytest.mark.asyncio
async def test_same_run_copies_become_repeats_of_the_kept_one(mocker):
    from src.services.job_searcher import repair

    keep = _stored(1, "applied", click_count=2)
    dropped = _stored(0, "not_interested")
    jobs = _FakeJobs([dropped, keep])

    async def aggregate(_pipeline):
        async def rows():
            yield {"_id": {"p": "Dou", "j": "370398"}, "n": 2}

        return rows()

    jobs.aggregate = aggregate
    mocker.patch.object(repair, "jobs_collection", jobs)
    now = datetime(2026, 11, 5, 15)

    assert await repair.mark_same_run_copies(now) == 1

    (query, update), *_ = jobs.updates
    assert query == {"_id": dropped["_id"], "user_status": "not_interested"}  # compare-and-set
    assert update["$set"] == {"user_status": "duplicate", "group_id": str(keep["_id"]),
                              "similar_to": str(keep["_id"]), "similar_to_platform": "Dou"}  # fmt: skip
    event = update["$push"]["history"]
    assert (event["from"], event["to"], event["actor"], event["cause"]) == (
        "not_interested", "duplicate", "system", repair.SAME_RUN_CAUSE,
    )  # fmt: skip
    # The dropped copy was its own root: whatever pointed at it now points at the kept one.
    jobs.update_many.assert_awaited_once_with(
        {"group_id": str(dropped["_id"])}, {"$set": {"group_id": str(keep["_id"])}}
    )
