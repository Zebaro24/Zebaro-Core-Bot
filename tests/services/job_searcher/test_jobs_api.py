import asyncio
import json
import re
import sys
from datetime import datetime, timedelta
from operator import itemgetter
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from bson import ObjectId
from pymongo.errors import ServerSelectionTimeoutError

mock_settings = MagicMock()
mock_settings.app_name = "test"
mock_settings.description = ""
mock_settings.version = "0.0.0"
mock_settings.debug = False
mock_settings.telegram_docker_access_ids = [123]
mock_settings.jobs_api_token = "api-token"
mock_settings.tz = "Europe/Berlin"

sys.modules["src.config"] = MagicMock(settings=mock_settings)
sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

from src.interfaces.webhooks.main import app  # noqa: E402
from src.services.job_searcher import jobs_api  # noqa: E402
from src.services.job_searcher.jobs_api import InvalidParameter, public_status, url_pattern  # noqa: E402
from src.services.job_searcher.words import has_word, parse_words  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "jobs-api.md"
AUTH = {"Authorization": "Bearer api-token"}
NOW = datetime(2026, 10, 29, 12, 0, 0)


# --- an in-memory collection ---------------------------------------------------------------------
# CI has no MongoDB. The fake knows only the operators the API uses and fails loudly on any other,
# so a query it accepts means the same here and in the database. $regex runs through Python's `re`:
# words.py writes its patterns so that the two engines agree.


def _equal(value: Any, target: Any) -> bool:
    if isinstance(target, re.Pattern):
        return isinstance(value, str) and target.search(value) is not None
    if target is None:
        return value is None  # MongoDB: null matches a missing field too
    return bool(value == target)


def _match_value(value: Any, condition: Any) -> bool:
    if not (isinstance(condition, dict) and condition and all(key.startswith("$") for key in condition)):
        return _equal(value, condition)
    for op, arg in condition.items():
        if op == "$in":
            ok = any(_equal(value, item) for item in arg)
        elif op == "$ne":
            ok = not _equal(value, arg)
        elif op == "$gte":
            ok = value is not None and value >= arg
        elif op == "$lt":
            ok = value is not None and value < arg
        elif op == "$regex":
            ok = isinstance(value, str) and re.search(arg, value) is not None
        else:
            raise NotImplementedError(op)
        if not ok:
            return False
    return True


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, condition in query.items():
        if key == "$and":
            ok = all(_matches(doc, part) for part in condition)
        elif key == "$or":
            ok = any(_matches(doc, part) for part in condition)
        elif key == "$nor":
            ok = not any(_matches(doc, part) for part in condition)
        elif key.startswith("$"):
            raise NotImplementedError(key)
        else:
            ok = _match_value(doc.get(key), condition)
        if not ok:
            return False
    return True


def _project(doc: dict[str, Any], projection: dict[str, int] | None) -> dict[str, Any]:
    if not projection:
        return dict(doc)
    if all(flag == 0 for flag in projection.values()):
        return {key: value for key, value in doc.items() if key not in projection}
    return {key: value for key, value in doc.items() if projection.get(key) or key == "_id"}


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, keys: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(keys):
            self._docs.sort(key=itemgetter(key), reverse=direction < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        self._docs = self._docs[:count]
        return self

    def __aiter__(self) -> "FakeCursor":
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeJobs:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = list(docs or [])

    def find(self, query: dict[str, Any], projection: dict[str, int] | None = None) -> FakeCursor:
        return FakeCursor([_project(doc, projection) for doc in self.docs if _matches(doc, query)])

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next((dict(doc) for doc in self.docs if _matches(doc, query)), None)


# --- fixtures ------------------------------------------------------------------------------------


def _doc(title: str = "Python Developer", minutes_ago: int = 60, **fields: Any) -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "platform_name": "Dou",
        "title": title,
        "company": "Acme",
        "description": "We build things in Python.",
        "link": "https://jobs.dou.ua/companies/acme/vacancies/1/",
        "found_at": NOW - timedelta(minutes=minutes_ago),
        "moderation": "sent",
        "user_status": "pending",
        **fields,
    }


@pytest.fixture
def jobs(mocker):
    fake = FakeJobs()
    mocker.patch.object(jobs_api, "jobs_collection", fake)
    mocker.patch.object(jobs_api, "settings", mock_settings)
    mocker.patch("src.interfaces.webhooks.routes.jobs.settings", mock_settings)
    return fake


class Client:
    """A synchronous client over the app; starlette's TestClient wants httpx2."""

    def get(self, path: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        async def call() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                return await http.get(path, params=params, headers=headers)

        return asyncio.run(call())


@pytest.fixture
def client(jobs):
    return Client()


def _get(client: Client, path: str, **params: Any) -> Any:
    params.setdefault("from", "2026-09-01")
    params.setdefault("to", "2026-11-01")
    return client.get(path, params=params, headers=AUTH)


# --- whole words ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "word", "found"),
    [
        ("AI Engineer", "ai", True),
        ("AI/ML Engineer", "ai", True),
        ("AI-powered product", "ai", True),
        ("Python (AI)", "ai", True),
        ("Email marketing manager", "ai", False),
        ("Model training pipelines", "ai", False),
        ("Джун Python", "джун", True),
        ("Джуніор Python", "джун", False),
        ("Розробник ШІ-систем", "ші", True),
        ("C# developer", "c#", True),
        ("React / Next.js", "next.js", True),
        ("React / NextJS", "next.js", False),
        ("Machine\n  Learning engineer", "machine learning", True),
        ("Python3 scripts", "python", False),
    ],
)
def test_a_word_matches_whole_and_in_any_case(text, word, found):
    assert has_word(text, word) is found


def test_words_are_split_by_commas_trimmed_and_lowered():
    assert parse_words(" AI, llm ,, Machine   Learning, ai") == ["ai", "llm", "machine learning"]


# --- statuses and links --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user_status", "outcome", "status"),
    [
        ("pending", None, "new"),
        ("applied", None, "applied"),
        ("applied", "reply", "replied"),
        ("applied", "interview", "interview"),
        ("applied", "offer", "offer"),
        ("applied", "rejected", "rejected_by_employer"),
        ("mismatch", None, "mismatch"),
        ("not_interested", None, "not_interested"),
        ("blocked", None, "blocked"),
        ("duplicate", None, "duplicate"),
    ],
)
def test_the_public_status_folds_the_answer_and_the_outcome(user_status, outcome, status):
    assert public_status({"user_status": user_status, "outcome": outcome}) == status


def test_a_link_from_an_email_finds_the_stored_one():
    pattern = url_pattern("https://WWW.Robota.ua/vacancy/123/?utm_source=mail#apply")
    assert re.search(pattern, "https://robota.ua/vacancy/123")
    assert re.search(pattern, "https://www.robota.ua/vacancy/123/")
    assert not re.search(pattern, "https://robota.ua/vacancy/1234")


def test_a_link_without_a_host_is_refused():
    with pytest.raises(InvalidParameter, match="url"):
        url_pattern("not a link")


# --- GET /jobs --------------------------------------------------------------------------------


def test_without_the_token_the_answer_is_401_in_the_api_format(client):
    response = client.get("/jobs")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_without_the_token_a_bad_parameter_is_still_a_401(client):
    response = client.get("/jobs", params={"limit": 500})
    assert response.status_code == 401


def test_a_status_the_contract_does_not_know_yet_does_not_break_the_page(client, jobs):
    jobs.docs.append(_doc("Odd", user_status="archived"))

    response = _get(client, "/jobs")

    assert response.status_code == 200 and response.json()["items"][0]["status"] == "archived"


def test_the_list_hides_repeats_and_filtered_out_and_has_no_text(client, jobs):
    sent = _doc("Python Developer")
    jobs.docs += [sent, _doc("Repeat", user_status="duplicate"), _doc("Senior", moderation="rejected_by_filter")]

    body = _get(client, "/jobs").json()

    assert body["scope"] == "own_searches"
    assert [item["id"] for item in body["items"]] == [str(sent["_id"])]
    item = body["items"][0]
    assert "description" not in item
    assert item["found_at"] == "2026-10-29T11:00:00Z"
    assert item["status"] == "new" and item["tier"] == "sent"
    assert body["next_cursor"] is None


def test_the_list_filters_by_stage_and_tier(client, jobs):
    interview = _doc("A", user_status="applied", outcome="interview")
    jobs.docs += [interview, _doc("B", user_status="applied"), _doc("C", moderation="rejected_by_filter")]

    assert [i["id"] for i in _get(client, "/jobs", status="interview").json()["items"]] == [str(interview["_id"])]
    assert [i["title"] for i in _get(client, "/jobs", tier="filtered_out").json()["items"]] == ["C"]


def test_any_finds_ai_in_titles_but_not_email(client, jobs):
    jobs.docs += [_doc("AI Engineer", 1), _doc("Email Marketing", 2), _doc("Senior AI/ML Engineer", 3)]

    titles = [i["title"] for i in _get(client, "/jobs", any="ai,llm", none="senior", where="title").json()["items"]]

    assert titles == ["AI Engineer"]


def test_all_needs_every_word_in_the_title_or_the_text(client, jobs):
    jobs.docs += [
        _doc("Python Developer", 1, description="FastAPI and React"),
        _doc("Python Developer", 2, description="Django only"),
    ]

    items = _get(client, "/jobs", all="python,react").json()["items"]

    assert len(items) == 1 and items[0]["found_at"] == "2026-10-29T11:59:00Z"


def test_company_and_link_find_the_vacancy_from_an_email(client, jobs):
    target = _doc("Backend", company="ТОВ Рога і Копита", link="https://djinni.co/jobs/712345-backend/")
    jobs.docs += [target, _doc("Other")]

    by_company = _get(client, "/jobs", company="рога").json()["items"]
    by_link = _get(client, "/jobs", url="djinni.co/jobs/712345-backend?utm_source=email").json()["items"]

    assert [i["id"] for i in by_company] == [i["id"] for i in by_link] == [str(target["_id"])]


@pytest.mark.parametrize(
    ("params", "name"),
    [
        ({"limit": 500}, "limit"),
        ({"status": "hired"}, "status"),
        ({"from": "2026-11-01", "to": "2026-10-01"}, "from"),
        ({"from": "yesterday"}, "from"),
        ({"cursor": "garbage"}, "cursor"),
        ({"cursor": "eyJmIjoiMjAyNi0xMC0wMVQwMDowMDowMCIsImkiOiJ4In0"}, "cursor"),  # {"f": <date>, "i": "x"}
        ({"url": "http://[abc"}, "url"),
        ({"where": "company"}, "where"),
        ({"url": "nothing"}, "url"),
    ],
)
def test_a_bad_parameter_is_a_400_naming_it(client, params, name):
    response = _get(client, "/jobs", **params)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_parameter" and error["message"].startswith(name)


def test_an_empty_period_is_an_empty_list_not_an_error(client):
    response = _get(client, "/jobs")
    assert response.status_code == 200 and response.json()["items"] == []


def test_pages_keep_no_repeats_and_no_gaps_while_new_vacancies_arrive(client, jobs):
    jobs.docs += [_doc(f"Job {n}", minutes_ago=n + 10) for n in range(120)]
    first = _get(client, "/jobs", limit=50).json()

    jobs.docs += [_doc(f"New {n}", minutes_ago=n) for n in range(5)]  # found while paging
    second = _get(client, "/jobs", limit=50, cursor=first["next_cursor"]).json()
    third = _get(client, "/jobs", limit=50, cursor=second["next_cursor"]).json()

    ids = [i["id"] for page in (first, second, third) for i in page["items"]]
    assert len(ids) == len(set(ids)) == 120
    assert third["next_cursor"] is None


def test_vacancies_found_at_the_same_moment_page_by_id(client, jobs):
    jobs.docs += [_doc(f"Same {n}", minutes_ago=5) for n in range(7)]
    first = _get(client, "/jobs", limit=3).json()
    rest = _get(client, "/jobs", limit=10, cursor=first["next_cursor"]).json()

    ids = [i["id"] for i in first["items"] + rest["items"]]
    assert len(set(ids)) == 7


def test_storage_down_is_a_503(client, jobs, mocker):
    down = ServerSelectionTimeoutError("no servers")
    mocker.patch.object(jobs_api, "jobs_collection", MagicMock(find=MagicMock(side_effect=down)))

    response = _get(client, "/jobs")

    assert response.status_code == 503 and response.json()["error"]["code"] == "storage_unavailable"


# --- GET /jobs/{id} ---------------------------------------------------------------------------


def test_one_vacancy_comes_with_its_text_and_copies(client, jobs):
    copy_id = str(ObjectId())
    doc = _doc(
        copies=[{"platform": "Djinni", "id": copy_id}], date=datetime(2026, 10, 28), applicants=37, warnings=["english"]
    )
    jobs.docs.append(doc)

    body = client.get(f"/jobs/{doc['_id']}", headers=AUTH).json()

    assert body["description"] == "We build things in Python."
    assert body["copies"] == [{"id": copy_id, "source": "Djinni"}]
    assert body["published_at"] == "2026-10-28T00:00:00Z"
    assert (body["applicants"], body["warnings"]) == (37, ["english"])


@pytest.mark.parametrize("job_id", [str(ObjectId()), "not-an-id"])
def test_an_unknown_vacancy_is_a_404(client, job_id):
    response = client.get(f"/jobs/{job_id}", headers=AUTH)
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_a_repeat_points_at_the_copy_that_holds_the_decision(client, jobs):
    root = _doc("Python Developer", 30, user_status="duplicate")
    decided = _doc("Python Developer", 20, platform_name="Djinni", user_status="applied", group_id=str(root["_id"]))
    repeat = _doc("Python Developer", 10, user_status="duplicate", group_id=str(root["_id"]))
    jobs.docs += [root, decided, repeat]

    body = client.get(f"/jobs/{repeat['_id']}", headers=AUTH).json()

    assert body["status"] == "duplicate" and body["duplicate_of"] == str(decided["_id"])


def test_without_a_decided_copy_a_repeat_points_at_the_pending_one(client, jobs):
    blocked = _doc("Python Developer", 30, platform_name="Djinni", user_status="blocked")
    pending = _doc("Python Developer", 20, user_status="pending", group_id=str(blocked["_id"]))
    repeat = _doc("Python Developer", 10, platform_name="Djinni", user_status="duplicate", group_id=str(blocked["_id"]))
    jobs.docs += [repeat, blocked, pending]

    body = client.get(f"/jobs/{repeat['_id']}", headers=AUTH).json()

    assert body["duplicate_of"] == str(pending["_id"])


# --- GET /jobs/funnel -------------------------------------------------------------------------


def _funnel_fixture() -> list[dict[str, Any]]:
    return [
        _doc("A", 1, matched_stack=["Python"], user_status="applied", outcome="interview"),
        _doc("B", 2, matched_stack=["Python"], user_status="applied", outcome="rejected"),
        _doc("C", 3, matched_stack=["React"], user_status="applied"),
        _doc("D", 4, user_status="mismatch", status_reason="english"),
        _doc("E", 5),
        _doc("F", 6, moderation="rejected_by_filter", filter_reason="senior"),
        _doc("G", 7, user_status="duplicate"),
    ]


def test_the_funnel_counts_stages_and_reasons(client, jobs):
    jobs.docs += _funnel_fixture()

    body = _get(client, "/jobs/funnel").json()

    assert body["scope"] == "own_searches" and body["from"] == "2026-09-01T00:00:00Z"
    group = body["groups"][0]
    assert (group["found"], group["filtered_out"], group["surfaced"], group["decided"], group["new"]) == (6, 1, 5, 4, 1)
    assert group["reached"] == {"applied": 3, "replied": 2, "interview": 1, "offer": 0}
    assert group["rejected_after"]["unknown"] == 1
    assert group["reasons"]["mismatch"] == {"english": 1}
    assert group["reasons"]["filtered_out"] == {"senior": 1}


def test_the_funnel_by_stack_counts_a_vacancy_in_each_of_its_technologies(client, jobs):
    jobs.docs += [_doc("A", matched_stack=["Python"], matched_bonus=["React"]), _doc("B", matched_stack=["Python"])]

    groups = {g["key"]: g["found"] for g in _get(client, "/jobs/funnel", group_by="stack").json()["groups"]}

    assert groups == {"Python": 2, "React": 1}


def test_the_funnel_by_week_uses_local_iso_weeks(client, jobs):
    # Sunday 23:30 UTC is already Monday in Berlin — the next ISO week.
    jobs.docs.append({**_doc("Late"), "found_at": datetime(2026, 10, 25, 23, 30)})

    keys = [g["key"] for g in _get(client, "/jobs/funnel", group_by="week").json()["groups"]]

    assert keys == ["2026-W44"]


def test_an_empty_funnel_is_zeros(client):
    group = _get(client, "/jobs/funnel").json()["groups"][0]
    assert group["found"] == 0 and group["reached"]["applied"] == 0


def test_an_unknown_grouping_is_a_400(client):
    assert _get(client, "/jobs/funnel", group_by="company").status_code == 400


# --- the contract and the old routes -------------------------------------------------------------


def _contract_json(after_heading: str) -> dict[str, Any]:
    text = CONTRACT.read_text(encoding="utf-8")
    section = text[text.index(after_heading) :]
    block = section[section.index("```json") + len("```json") : section.index("```", section.index("```json") + 7)]
    example: dict[str, Any] = json.loads(block)
    return example


def test_the_list_example_in_the_contract_is_a_real_answer(client, jobs):
    example = _contract_json("## GET /jobs — список")["items"][0]
    jobs.docs.append(
        {
            "_id": ObjectId(example["id"]),
            "platform_name": "Djinni",
            "title": example["title"],
            "company": example["company"],
            "description": "…",
            "link": example["url"],
            "found_at": datetime(2026, 10, 28, 9, 12, 44),
            "date": datetime(2026, 10, 28),
            "moderation": "top",
            "user_status": "pending",
            "matched_stack": ["Python", "FastAPI"],
            "matched_bonus": ["LLM"],
            "work_format": "remote",
            "english": "B1",
            "required_years": 2,
            "salary": example["salary"],
            "search_url": example["search"],
        }
    )

    body = _get(client, "/jobs").json()

    assert body["items"] == [example]


def test_the_funnel_example_in_the_contract_has_the_real_shape(client, jobs):
    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shape(item) for key, item in value.items()}
        return type(value).__name__

    example = _contract_json("## GET /jobs/funnel")
    jobs.docs += _funnel_fixture()
    real = _get(client, "/jobs/funnel").json()

    example_group, real_group = example.pop("groups")[0], real.pop("groups")[0]
    assert shape(real) == shape(example)
    assert set(real_group) == set(example_group)
    assert set(real_group["reasons"]) == set(example_group["reasons"])
    assert set(real_group["status"]) == set(example_group["status"])


def test_the_schema_lists_the_api_routes():
    schema = app.openapi()
    assert {"/jobs", "/jobs/funnel", "/jobs/digest", "/jobs/{job_id}"} <= set(schema["paths"])
    assert "from" in schema["components"]["schemas"]["Funnel"]["properties"]


def test_the_vacancy_link_stays_public_and_answers_in_fastapis_format(client, mocker):
    from src.interfaces.webhooks.routes import jobs as routes

    mocker.patch.object(routes, "jobs_collection", MagicMock(find_one_and_update=AsyncMock(return_value=None)))

    response = client.get(f"/jobs/r/{ObjectId()}", headers={})

    assert response.status_code == 404 and response.json() == {"detail": "Job not found"}


# --- what moved here from the old routes ----------------------------------------------------------


def test_the_list_finds_by_the_old_search_parameters(client, jobs):
    target = _doc(
        "Target", 1, job_id="712345", filter_reason=None, user_status="mismatch", status_reason="english",
        search_url="https://djinni.co/jobs/?primary_keyword=Python",
    )  # fmt: skip
    jobs.docs += [target, _doc("Other", 2, job_id="1", search_url="https://jobs.dou.ua/vacancies/?category=Python")]

    for params in (
        {"source_id": "712345"},
        {"reason_code": "english,experience"},
        {"search": "PRIMARY_keyword=python"},  # any case
    ):
        items = _get(client, "/jobs", **params).json()["items"]
        assert [i["id"] for i in items] == [str(target["_id"])], params


def test_the_list_finds_the_filtered_out_by_reason(client, jobs):
    jobs.docs += [
        _doc("A", 1, moderation="rejected_by_filter", filter_reason="senior"),
        _doc("B", 2, moderation="rejected_by_filter", filter_reason="office"),
    ]

    with_tier = _get(client, "/jobs", tier="filtered_out", filter_reason="senior").json()["items"]
    without_tier = _get(client, "/jobs", filter_reason="senior").json()["items"]

    assert [i["title"] for i in with_tier] == [i["title"] for i in without_tier] == ["A"]


def test_the_list_carries_texts_only_when_asked(client, jobs):
    jobs.docs.append(_doc())

    plain = _get(client, "/jobs").json()["items"][0]
    full = _get(client, "/jobs", with_description="true").json()["items"][0]

    assert "description" not in plain
    assert full["description"] == "We build things in Python."


def test_the_funnel_by_search_compares_searches_with_a_label(client, jobs):
    url = "https://djinni.co/jobs/?primary_keyword=Python"
    jobs.docs += [
        _doc("A", 60, search_url=url, user_status="applied", click_count=2, status_updated_at=NOW),
        _doc("B", 120, search_url=url, user_status="not_interested", status_reason="role", status_updated_at=NOW),
        _doc("C", 3, search_url=url, user_status="duplicate"),
        _doc("D", 4, search_url=url, moderation="top"),
        _doc("E", 5),
    ]

    groups = {g["key"]: g for g in _get(client, "/jobs/funnel", group_by="search").json()["groups"]}

    djinni = groups[url]
    assert djinni["label"] == "Djinni · Python"
    assert (djinni["found"], djinni["repeats"], djinni["opened"], djinni["clicks"]) == (3, 1, 1, 2)
    assert djinni["tiers"]["top"] == 1 and djinni["tiers"]["sent"] == 2
    assert djinni["apply_rate"] == 0.5 and djinni["reply_rate"] == 0.0
    assert djinni["median_hours_to_decision"] == 1.5
    assert groups["(unknown)"]["found"] == 1


def test_the_digest_is_the_friday_numbers_with_utc_dates(client, mocker):
    from src.interfaces.webhooks.routes import jobs as routes

    digest = {
        "period_days": 7, "since": datetime(2026, 10, 22, 12), "until": NOW,
        "market": {"in_field": 3}, "me": {"decisions": {"applied": 1}},
        "market_insights": [], "my_insights": [{"kind": "backlog", "old": 2}], "silent_sources": ["Work.ua"],
    }  # fmt: skip
    get_digest = mocker.patch.object(routes, "get_digest", new=AsyncMock(return_value=digest))

    body = client.get("/jobs/digest", params={"days": 7}, headers=AUTH).json()

    get_digest.assert_awaited_once_with(7, strict=True)
    assert body["scope"] == "own_searches"
    assert (body["from"], body["to"]) == ("2026-10-22T12:00:00Z", "2026-10-29T12:00:00Z")
    assert body["silent_sources"] == ["Work.ua"] and body["my_insights"][0]["kind"] == "backlog"


def test_the_digest_with_the_db_down_is_a_503_not_an_empty_week(client, mocker):
    from src.services.job_searcher import digest

    down = MagicMock(find=MagicMock(side_effect=ServerSelectionTimeoutError("no servers")))
    mocker.patch.object(digest, "jobs_collection", down)

    response = client.get("/jobs/digest", headers=AUTH)

    assert response.status_code == 503 and response.json()["error"]["code"] == "storage_unavailable"


def test_the_digest_period_is_checked(client):
    response = client.get("/jobs/digest", params={"days": 365}, headers=AUTH)
    assert response.status_code == 400 and response.json()["error"]["message"].startswith("days")


def test_silent_sources_are_the_searched_boards_that_found_nothing(mocker):
    from src.services.job_searcher import digest

    mocker.patch("src.services.job_searcher.parser.platform_names", return_value={"Djinni", "Dou", "Work.ua"})

    assert digest._silent([{"platform_name": "Djinni"}]) == ["Dou", "Work.ua"]
    assert digest._silent([]) == []  # nothing at all says nothing about a board
