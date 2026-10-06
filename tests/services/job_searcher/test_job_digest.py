import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.tg.formatters.job_stats import (
    format_digest_plain,
    format_market_rich,
    format_me_rich,
)
from src.services.job_searcher.digest import (
    market_insights,
    market_stats,
    my_insights,
    my_stats,
    salary_value,
    search_label,
)

NOW = datetime(2026, 10, 6, 12)


def _doc(**fields):
    base = {"platform_name": "Dou", "moderation": "review", "user_status": "pending", "found_at": NOW}
    return {**base, **fields}


def test_market_counts_only_his_field_and_reads_the_asks():
    found = [
        _doc(required_years=2, english="B1", matched_stack=["Python"], salary="$2000–3000"),
        _doc(required_years=3, english="B2", matched_stack=["Python", "React"], matched_bonus=["Docker"]),
        _doc(moderation="rejected_by_filter", filter_reason="experience", required_years=5, english="C1"),
        _doc(moderation="rejected_by_filter", filter_reason="other stack"),  # not his field
    ]
    found_prev = [_doc(matched_stack=["React"])] * 2

    market = market_stats(found, found_prev)

    assert market["in_field"] == 3 and market["surfaced"] == 2 and market["in_field_prev"] == 2
    assert market["years"] == {"≤1": 0, "2": 1, "3": 1, "4+": 1, "?": 0}
    assert market["english"] == {"≤B1": 1, "B2": 1, "C1+": 1, "?": 0}
    python = market["top_tech"][0]
    assert python == {"name": "Python", "share": 1.0, "delta": 1.0}  # absent last week: came from nothing
    react = next(tech for tech in market["top_tech"] if tech["name"] == "React")
    assert react["delta"] == pytest.approx(-0.5)
    assert market["blockers"] == {"experience": 1}
    assert market["salary"] is None  # one salary is not a median


def test_market_insights_name_the_wall_and_the_trends():
    found = [_doc(moderation="rejected_by_filter", filter_reason="senior")] * 6 + [
        _doc(english="B2", matched_stack=["Python"]),
        _doc(english="B1", matched_stack=["Python"]),
    ] * 3
    market = market_stats(found, [_doc(matched_stack=["React"])] * 20)

    kinds = [item["kind"] for item in market_insights(market)]

    assert kinds[0] == "seniority_wall"
    assert "english_gate" in kinds and "tech_rising" in kinds and "volume" in kinds


def test_my_week_counts_the_funnel_answers_reasons_and_filter_misses():
    answered = NOW - timedelta(hours=5)
    this_week = [
        _doc(user_status="applied", status_updated_at=answered, moderation="top", click_count=2),
        _doc(user_status="mismatch", status_reason="experience", required_years=4, status_updated_at=answered,
             moderation="sent"),
        _doc(user_status="blocked", platform_name="Djinni", status_updated_at=answered),
        _doc(user_status="not_interested", status_reason="role", status_updated_at=answered),
    ]  # fmt: skip
    last_week = [_doc(user_status="applied", status_updated_at=NOW - timedelta(days=8))] * 3
    pending = [_doc(found_at=NOW - timedelta(days=5)), _doc()]
    found = [*this_week, _doc(moderation="rejected_by_filter")]

    me = my_stats(this_week, last_week, this_week, pending, NOW, found)

    assert me["decisions"] == {"applied": 1, "mismatch": 1, "not_interested": 1, "blocked": 1}
    assert me["funnel"] == {"found": 5, "surfaced": 4, "opened": 1, "applied": 1}
    assert me["prev"]["applied"] == 3
    assert me["apply_rate"] == 0.25
    assert me["mismatch_reasons"] == {"experience": 1, "site": 1}
    assert me["not_interested_reasons"] == {"role": 1}
    assert me["filter_misses"]["mismatch"] == 1 and me["filter_misses"]["promised"] == 2
    assert me["pending"] == {"count": 2, "old": 1}
    assert me["searches"] is None  # no search has enough answers yet


def test_my_insights_compare_sites_and_tiers():
    dou = [_doc(user_status="applied", moderation="top", status_updated_at=NOW)] * 6
    djinni = [_doc(user_status="blocked", platform_name="Djinni", moderation="review", status_updated_at=NOW)] * 6
    me = my_stats(dou + djinni, [], dou + djinni, [], NOW, [])

    kinds = {item["kind"]: item for item in my_insights(me, market_stats([]))}

    assert kinds["platform_gap"]["best"] == "Dou" and kinds["platform_gap"]["worst_blocked"] == 6
    assert kinds["tiers"]["top"] == 1.0 and kinds["tiers"]["review"] == 0.0
    assert kinds["main_gap"]["reason"] == "site"


@pytest.mark.parametrize(
    "text,value",
    [("$3500–4500", 4000), ("до $2500", 2500), ("від $3 000", 3000), ("20 000 грн", None), (None, None)],
)
def test_salary_value(text, value):
    assert salary_value(text) == value


@pytest.mark.parametrize(
    "url,label",
    [
        ("https://jobs.dou.ua/vacancies/?remote&category=Python", "DOU · Python remote"),
        ("https://djinni.co/jobs/keyword-python/?employment=remote&exp_level=1y", "Djinni · python"),
        ("https://djinni.co/jobs/?all_keywords=FastAPI&employment=remote", "Djinni · FastAPI"),
        ("https://www.work.ua/jobs-remote-python+developer/", "Work.ua · remote python developer"),
        (None, "?"),
    ],
)
def test_search_label(url, label):
    assert search_label(url) == label


def _digest():
    found = [
        _doc(required_years=2, english="B2", matched_stack=["Python"], moderation="top"),
        _doc(moderation="rejected_by_filter", filter_reason="senior"),
    ]
    answered = [_doc(user_status="applied", status_updated_at=NOW, platform_name="<b>Dou</b>")]
    market = market_stats(found, [])
    me = my_stats(answered, [], answered, [], NOW, found)
    return {
        "period_days": 7,
        "since": NOW - timedelta(days=7),
        "until": NOW,
        "market": market,
        "me": me,
        "market_insights": market_insights(market),
        "my_insights": my_insights(me, market),
        "silent_sources": ["Work.ua"],
    }


def test_the_digest_renders_in_two_messages_and_a_plain_fallback():
    digest = _digest()

    market, me, plain = format_market_rich(digest), format_me_rich(digest), format_digest_plain(digest)

    assert "Кого ищут компании" in market and "29.09 — 06.10.2026" in market
    assert "<pre>" in market and "Что отсекает тебя" in market and "💡 Выводы" in market
    assert "Твои отклики" in me and "Воронка недели" in me
    assert "Ничего не дали за период: <b>Work.ua</b>" in me
    assert "<b>Dou</b>" not in me and "&lt;b&gt;Dou&lt;/b&gt;" in me  # names are escaped
    assert "Вакансии за 7 дней" in plain


def test_the_owner_is_marked_on_the_charts():
    market = format_market_rich(_digest())

    assert "до B1" in market and "← ты" in market
