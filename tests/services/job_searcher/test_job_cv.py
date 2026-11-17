import sys
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.tg.formatters.job import cover_letter_html, cv_line, gaps_line, job_to_rich_html
from src.interfaces.tg.formatters.job_stats import format_me_rich
from src.services.job_searcher import cv, letters, repair, status
from src.services.job_searcher.container import Job
from src.services.job_searcher.digest import cv_stats, cv_used, my_insights
from src.services.job_searcher.filter import evaluate, title_reject_reason
from src.services.job_searcher.jobs_api import funnel_groups, group_keys

LONG = "We build a product for logistics companies and care about clean code. " * 4


@pytest.mark.parametrize(
    "title,description,track",
    [
        ("AI Engineer", "Python, LLM", cv.AI),
        ("AI/ML Engineer (LLM)", "Python", cv.AI),
        ("Python Developer (AI agents)", "FastAPI", cv.AI),
        ("Full Stack Developer", "Python, React", cv.FULLSTACK),
        ("Python / React Developer", "", cv.FULLSTACK),
        ("Python Developer", "Django, PostgreSQL", cv.BACKEND),
        ("Backend Engineer", "FastAPI. Nice to have:\nReact", cv.BACKEND),
        ("Software Engineer", "Requirements:\nPython, FastAPI\nReact, Next.js", cv.FULLSTACK),
        ("Software Engineer", "Python and Django", cv.BACKEND),
    ],
)
def test_a_vacancy_is_routed_to_one_of_the_three_cvs(title, description, track):
    assert cv.route(title, description) == track


@pytest.mark.parametrize(
    "title,reason",
    [
        ("Data Engineer (Python)", "off track"),
        ("Middle ML Engineer", "off track"),
        ("Data Scientist", "off track"),
        ("DevOps Engineer", "off track"),
        ("Computer Vision Engineer", "off track"),
        ("AI/ML Engineer", None),  # the AI word keeps it: the AI CV
        ("Research Engineer (LLM)", None),
        ("Shopify Developer", "other stack"),
    ],
)
def test_roles_no_cv_is_for_are_skipped_by_the_title(title, reason):
    assert title_reject_reason(title, "Acme") == reason


def test_the_fit_lists_the_cv_skills_and_what_it_lacks():
    description = "Requirements:\nPython, FastAPI, PostgreSQL, Celery, AWS\nNice to have:\nKafka"
    fit = cv.fit(cv.BACKEND, "Python Developer", description)
    assert fit.match == ["Python", "FastAPI", "PostgreSQL"]
    assert fit.gaps == ["Celery", "AWS"]
    assert fit.gaps_plus == ["Kafka"]


def test_a_python_backend_is_on_target_for_the_backend_cv():
    verdict = evaluate(Job(title="Middle Python Developer", description=f"Python, FastAPI, PostgreSQL, Docker. {LONG}"))
    assert verdict.moderation == "top"
    assert verdict.cv_track == cv.BACKEND


def test_two_required_technologies_the_cv_lacks_keep_it_off_the_top():
    description = f"Python, FastAPI, Kubernetes, Kafka. {LONG}"
    verdict = evaluate(Job(title="Middle Python Developer", description=description))
    assert verdict.moderation == "sent"
    assert verdict.cv_fit is not None and verdict.cv_fit.gaps == ["Kafka", "Kubernetes"]


def test_an_ai_title_without_llm_work_is_only_partial():
    verdict = evaluate(Job(title="Middle AI Engineer", description=f"Python, pandas, scikit-learn. {LONG}"))
    assert verdict.moderation == "review" and verdict.cv_track == cv.AI


def test_the_message_names_the_cv_and_its_gaps():
    job = Job(
        title="Python Developer", platform_name="Djinni", moderation="top", cv_track=cv.BACKEND,
        cv_gaps=["Celery"], cv_gaps_plus=["Kafka"],
    )  # fmt: skip
    assert cv_line(job) == "📎 <b>CV: Python Backend Engineer</b> · на Djinni выбери его вместо основного"
    assert gaps_line(job) == "🧩 Нет в CV: Celery · плюсом: Kafka"
    assert "CV: Python Backend Engineer" in job_to_rich_html(job)
    # Djinni's main CV is the full-stack one: nothing to change there.
    assert cv_line(Job(platform_name="Djinni", cv_track=cv.FULLSTACK)) == "📎 <b>CV: Python Fullstack Engineer</b>"


def test_the_letter_follows_the_cv_and_the_vacancy_language():
    ua = cover_letter_html(Job(cv_track=cv.AI, description="Шукаємо AI інженера в команду", salary="$3000–4000"))
    assert "<b>AI Engineer</b> · UA" in ua
    assert "мультиагентним LLM-пайплайном" in ua
    assert "$3 500 net (середина их вилки)" in ua
    en = cover_letter_html(Job(cv_track=cv.BACKEND, description="We are looking for a Python developer"))
    assert "Last year I built a production AI SaaS for content creators" in en
    assert "$1 700 net" in en
    assert letters.letter(cv.FULLSTACK, letters.EN).endswith("Portfolio: zebaro.dev")


def test_the_salary_never_goes_below_the_floor():
    assert cv.salary_ask(cv.BACKEND, "до $1000") == (cv.SALARY_FLOOR, True)
    assert cv.salary_ask(cv.AI, None) == (2200, False)


def test_an_application_before_the_three_cvs_went_with_the_single_one():
    assert cv.sent_with(cv.AI, datetime(2026, 11, 1)) == cv.UNIVERSAL
    assert cv.sent_with(cv.AI, datetime(2026, 11, 10)) == cv.AI
    assert cv.sent_with(None, datetime(2026, 11, 10)) == cv.FULLSTACK
    assert cv_used({"cv_sent": cv.BACKEND, "cv_track": cv.AI}) == cv.BACKEND


def _applied(track: str, n: int, replied: int, when: datetime = datetime(2026, 11, 12)) -> list[dict]:
    return [
        {"user_status": "applied", "cv_sent": track, "cv_track": track, "status_updated_at": when,
         "outcome": "reply" if i < replied else None}
        for i in range(n)
    ]  # fmt: skip


def test_the_stats_per_cv_and_the_cv_to_rework_first():
    applied = _applied(cv.BACKEND, 20, 6) + _applied(cv.AI, 20, 1) + _applied(cv.UNIVERSAL, 5, 1)
    window = [{"cv_track": cv.BACKEND, "user_status": "applied"}] * 5 + [
        {"cv_track": cv.BACKEND, "user_status": "x"}
    ] * 5
    found = [{"cv_track": cv.AI, "moderation": "top"}, {"cv_track": cv.AI, "moderation": "rejected_by_filter"}]

    stats = cv_stats(applied, window, found)

    assert [row["cv"] for row in stats["sent"]] == [cv.BACKEND, cv.AI, cv.UNIVERSAL]
    assert stats["sent"][0]["replied"] == 6 and stats["sent"][0]["reply_rate"] == 0.3
    assert stats["apply_rate"] == [{"cv": cv.BACKEND, "decided": 10, "applied": 5, "rate": 0.5}]
    assert stats["market"] == {cv.BACKEND: 0, cv.FULLSTACK: 0, cv.AI: 1}

    me: dict[str, Any] = {
        "by_cv": stats, "by_platform": [], "by_tier_rate": {}, "mismatch_reasons": {}, "filter_misses": None,
        "avg_hours_to_action": None, "pending": {"old": 0}, "dead_searches": [],
        "decisions": {"applied": 0}, "prev": {"applied": 0},
    }  # fmt: skip
    insight = my_insights(me, {})[0]
    assert insight["kind"] == "cv_gap" and insight["worst"] == cv.AI and insight["best"] == cv.BACKEND


def test_the_digest_shows_the_cv_section():
    stats = cv_stats(_applied(cv.BACKEND, 6, 2), [], [])
    digest = {
        "period_days": 7, "since": datetime(2026, 11, 6), "until": datetime(2026, 11, 13),
        "me": {
            "decisions": {"applied": 0, "mismatch": 0, "not_interested": 0, "blocked": 0},
            "prev": {"applied": 0, "mismatch": 0, "not_interested": 0, "blocked": 0},
            "apply_rate": None, "avg_hours_to_action": None, "pending": {"count": 0, "old": 0},
            "funnel": {"found": 0}, "by_platform": [], "outcomes": None, "by_tier_rate": {},
            "mismatch_reasons": {}, "not_interested_reasons": {}, "applied_tech": [], "searches": None,
            "by_cv": stats,
        },
    }  # fmt: skip
    html = format_me_rich(digest)
    assert "📎 По резюме" in html and "Backend" in html and "2/6" in html


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for doc in self.docs:
            yield doc


@pytest.mark.asyncio
async def test_the_repair_fills_the_cvs_of_stored_vacancies(mocker):
    old = {"_id": 1, "title": "AI Engineer", "description": "LLM", "moderation": "top", "user_status": "applied",
           "status_updated_at": datetime(2026, 10, 1)}  # fmt: skip
    new = {"_id": 2, "title": "Python Developer", "description": "Django", "moderation": "sent",
           "user_status": "pending"}  # fmt: skip
    collection = mocker.patch.object(repair, "jobs_collection")
    collection.find = MagicMock(return_value=_Cursor([old, new]))
    collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    assert await repair.fill_cvs() == 3  # two tracks and one CV

    track_old, sent_old, track_new = collection.update_one.await_args_list
    assert track_old.args[0] == {"_id": 1, "cv_track": None}
    assert track_old.args[1]["$set"]["cv_track"] == cv.AI
    # A CV picked by a button meanwhile wins: the write is guarded by the empty field.
    assert sent_old.args[0] == {"_id": 1, "user_status": "applied", "cv_sent": None}
    assert sent_old.args[1] == {"$set": {"cv_sent": cv.UNIVERSAL}}
    assert track_new.args[1]["$set"]["cv_track"] == cv.BACKEND


@pytest.mark.parametrize(
    "doc,key",
    [
        ({"user_status": "applied", "cv_sent": cv.AI, "cv_track": cv.BACKEND}, cv.BACKEND),
        ({"user_status": "pending", "cv_track": cv.BACKEND}, cv.BACKEND),
        ({"user_status": "pending"}, "(none)"),
    ],
)
def test_the_funnel_groups_by_the_cv_the_vacancy_fits(doc, key):
    assert group_keys(doc, "cv") == [key]


def test_the_cv_funnel_tells_which_cv_the_applications_went_with():
    found = datetime(2026, 11, 1)
    base = {"moderation": "sent", "found_at": found, "cv_track": cv.BACKEND}
    docs = [
        {**base, "user_status": "applied", "cv_sent": cv.UNIVERSAL},
        {**base, "user_status": "applied", "cv_sent": cv.BACKEND},
        {**base, "user_status": "not_interested"},
        {**base, "cv_track": cv.AI, "user_status": "pending"},
    ]

    groups = {group["key"]: group for group in funnel_groups(docs, "cv")}

    assert set(groups) == {cv.BACKEND, cv.AI}  # no group of applications only
    backend = groups[cv.BACKEND]
    assert backend["applied_with"] == {cv.UNIVERSAL: 1, cv.BACKEND: 1}
    assert (backend["reached"]["applied"], backend["decided"], backend["apply_rate"]) == (2, 3, 0.667)


def _status_collection(mocker, doc):
    collection = mocker.patch.object(status, "jobs_collection")
    collection.find_one_and_update = AsyncMock(side_effect=lambda query, update, **_: {**doc, **update["$set"]})
    return collection


@pytest.mark.asyncio
async def test_an_application_stores_its_cv_and_an_old_one_keeps_the_single_cv(mocker):
    fresh = {"_id": 1, "user_status": "pending", "cv_track": cv.AI}
    collection = _status_collection(mocker, fresh)
    await status.write_status(fresh, "applied", expected="new", actor="user", sync=False)
    assert collection.find_one_and_update.await_args.args[1]["$set"]["cv_sent"] == cv.AI

    # An October application without a CV gets its reply today: the CV of October.
    old = {"_id": 2, "user_status": "applied", "cv_track": cv.AI, "status_updated_at": datetime(2026, 10, 1)}
    collection = _status_collection(mocker, old)
    await status.write_status(old, "replied", expected="applied", actor="user", sync=False)
    assert collection.find_one_and_update.await_args.args[1]["$set"]["cv_sent"] == cv.UNIVERSAL


@pytest.mark.asyncio
async def test_an_undone_application_drops_its_cv(mocker):
    doc = {"_id": 3, "user_status": "applied", "cv_sent": cv.AI}
    collection = _status_collection(mocker, doc)
    await status.write_status(doc, "new", expected="applied", actor="user", sync=False)
    assert collection.find_one_and_update.await_args.args[1]["$set"]["cv_sent"] is None
