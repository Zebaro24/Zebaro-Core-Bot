"""The Jobs API — the contract in docs/contracts/jobs-api.md, for the MCP's `jobs_*` tools.

Errors are `{"error": {"code", "message"}}`, not FastAPI's `{"detail"}`: the reader is an LLM,
and the message names the parameter and why. `/jobs/r/<id>` is apart: public, no token, the
click-tracked link behind every vacancy button in Telegram.
"""

import logging
import secrets
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from src.config import settings
from src.db import sql
from src.interfaces.tg.notification.job_status import kick_status_sync
from src.services.job_searcher import events, jobs_api, journal, status
from src.services.job_searcher.digest import get_digest
from src.services.job_searcher.jobs_api import GROUP_BY, STATUSES, TIERS, Filters, InvalidParameter
from src.services.job_searcher.reasons import public_reasons
from src.services.job_searcher.words import parse_words

logger = logging.getLogger("webhooks.jobs")

PREFIX = "/jobs"
MAX_LIMIT = 200


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def error_response(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc.status, exc.code, exc.message, **exc.extra)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """400 in the API's format under /jobs; every other route keeps FastAPI's own 422."""
    assert isinstance(exc, RequestValidationError)
    if not request.url.path.startswith(f"{PREFIX}/") and request.url.path != PREFIX:
        return await request_validation_exception_handler(request, exc)
    first = exc.errors()[0] if exc.errors() else {}
    name = str((first.get("loc") or ["?"])[-1])
    return error_response(400, "invalid_parameter", f"{name}: {first.get('msg', 'invalid value')}")


# --- response schemas (/openapi.json is half of the contract) ----------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    error: ErrorDetail


class JobCopy(BaseModel):
    id: str
    source: str
    status: str | None = Field(default=None, description="Its status; null for a stored copy no longer found")


class JobSummary(BaseModel):
    id: str
    title: str
    company: str | None
    source: str
    url: str
    found_at: str | None
    published_at: str | None
    # Plain strings, the enums in the description: a value the bot adds later must not fail the page.
    status: str = Field(description=" | ".join(STATUSES))
    status_reason_code: str | None
    status_reason: str | None
    status_changed_at: str | None
    tier: str = Field(description=" | ".join(TIERS))
    filter_reason: str | None
    stack: list[str]
    work_format: str | None
    english: str | None
    required_years: int | None
    salary: str | None
    search: str | None
    duplicate_of: str | None
    cv: str | None = Field(default=None, description="The CV it fits: backend | fullstack | ai")
    cv_sent: str | None = Field(
        default=None, description="The CV the application went with: backend | fullstack | ai | universal"
    )
    copies: list[JobCopy] = Field(
        default_factory=list,
        description="The same vacancy on other boards or reposted later (its group), oldest first",
    )


class JobListItem(JobSummary):
    description: str | None = Field(default=None, description="Only with with_description=true")


class HistoryEvent(BaseModel):
    id: str
    occurred_at: str | None = Field(description="When it happened (the e-mail's date); analytics go by it")
    recorded_at: str | None = Field(description="When the bot wrote it")
    from_: str = Field(alias="from")
    to: str
    actor: str = Field(description="ai | user | system")
    reason_code: str | None
    suggested_code: str | None
    reason: str | None
    evidence: str | None
    approximate: bool = Field(description="The time is a guess: kept out of the response times")
    undo_of: str | None = Field(description="The event this one took back")
    cause: str | None = Field(description="The event on another copy that made this one (a repeat)")


class JobFull(JobSummary):
    description: str
    location: str | None
    countries: str | None
    applicants: int | None
    warnings: list[str]
    cv_match: list[str] = Field(default_factory=list, description="The CV's skills the vacancy names")
    cv_gaps: list[str] = Field(default_factory=list, description="Required, and not in the CV")
    cv_gaps_plus: list[str] = Field(default_factory=list, description="Not in the CV, only nice to have")
    requirements: str | None = Field(
        default=None, description="The must-have section of the description as written; null when it has none"
    )
    work_hours: list[str] = Field(
        default_factory=list, description="The description's lines about hours, time zone or schedule"
    )
    history: list[HistoryEvent] = Field(default_factory=list, description="Status events, oldest first")


class StatusPatch(BaseModel):
    """PATCH /jobs/{id}/status. Unknown fields are refused: a typo must not pass as "no reason"."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description=" | ".join(status.WRITABLE))
    expected_status: str = Field(description="The status the client saw; another one now → 409")
    actor: str = Field(description="ai | user")
    reason_code: str | None = Field(default=None, description="From GET /jobs/reasons for the new status")
    suggested_code: str | None = Field(default=None, description="With reason_code 'other': the code that would fit")
    reason: str | None = Field(default=None, description="Free text: what exactly they said")
    evidence: str | None = Field(default=None, description="Required for ai: the Gmail message id or a quote")
    occurred_at: str | None = Field(default=None, description="When it happened, ISO 8601; default now")


class StatusResult(BaseModel):
    changed: bool
    job: JobFull
    telegram: str = Field(description="queued | skipped")


class Reason(BaseModel):
    code: str
    description: str


class ReasonList(BaseModel):
    statuses: dict[str, list[Reason]]


class JobList(BaseModel):
    scope: Literal["own_searches"]
    items: list[JobListItem]
    next_cursor: str | None


class Reached(BaseModel):
    applied: int
    replied: int
    interview: int
    offer: int


class RejectedAfter(BaseModel):
    applied: int
    replied: int
    interview: int
    unknown: int


class Reasons(BaseModel):
    rejected_by_employer: dict[str, int]
    mismatch: dict[str, int]
    not_interested: dict[str, int]
    filtered_out: dict[str, int]


class FunnelGroup(BaseModel):
    key: str
    label: str
    found: int
    repeats: int
    filtered_out: int
    surfaced: int
    tiers: dict[str, int]
    decided: int
    new: int
    opened: int
    clicks: int
    reached: Reached
    applied_with: dict[str, int] = Field(description="Applications by the CV they went with (cv_sent)")
    status: dict[str, int]
    rejected_after: RejectedAfter
    reasons: Reasons
    apply_rate: float | None
    reply_rate: float | None
    median_hours_to_decision: float | None


class JournalItem(BaseModel):
    id: str
    occurred_at: str | None
    recorded_at: str | None
    kind: str = Field(description=" | ".join(journal.KINDS))
    text: str
    actor: str


class Funnel(BaseModel):
    scope: Literal["own_searches"]
    by: Literal["found"] = "found"
    from_: str | None = Field(alias="from")
    to: str | None
    group_by: str
    groups: list[FunnelGroup]
    journal: list[JournalItem] | None = Field(
        default_factory=list, description="The owner's changes in the period; null when it could not be read"
    )
    journal_error: str | None = Field(
        default=None, description='unavailable: the journal could not be read; null journal is not "no changes"'
    )


class Transition(BaseModel):
    from_: str = Field(alias="from")
    to: str
    count: int


class TimeToReply(BaseModel):
    count: int
    median_hours: float | None
    p75_hours: float | None


class EventGroup(BaseModel):
    key: str
    label: str
    events: int
    entered: dict[str, int]
    transitions: list[Transition]
    applied: int
    reached: Reached
    rejections: dict[str, dict[str, int]] = Field(description="stage (from) → reason_code → count")
    reply_rate: float | None
    interview_rate: float | None
    time_to_reply: TimeToReply


class EventFunnel(BaseModel):
    scope: Literal["own_searches"]
    by: Literal["event"]
    from_: str | None = Field(alias="from")
    to: str | None
    group_by: str
    groups: list[EventGroup]
    journal: list[JournalItem] | None
    journal_error: str | None = Field(
        default=None, description='unavailable: the journal could not be read; null journal is not "no changes"'
    )


class JournalPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description=" | ".join(journal.KINDS))
    text: str = Field(description=f"What changed and why, up to {journal.MAX_TEXT} characters")
    occurred_at: str | None = Field(default=None, description="When the change was made, ISO 8601; default now")
    actor: str = Field(default="user", description=" | ".join(journal.ACTORS))


class JournalList(BaseModel):
    items: list[JournalItem]


class Digest(BaseModel):
    scope: Literal["own_searches"]
    period_days: int
    from_: str | None = Field(alias="from")
    to: str | None
    market: dict[str, Any]
    me: dict[str, Any]
    market_insights: list[dict[str, Any]]
    my_insights: list[dict[str, Any]]
    silent_sources: list[str]


_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorBody} for code in (400, 401, 404, 503)
}  # fmt: skip
_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {**_ERRORS, 409: {"model": ErrorBody}}


# --- parameters --------------------------------------------------------------------------------


def _check_token(request: Request) -> None:
    authorization = request.headers.get("Authorization") or ""
    if not settings.jobs_api_token or not secrets.compare_digest(authorization, f"Bearer {settings.jobs_api_token}"):
        raise ApiError(401, "unauthorized", "Missing or wrong bearer token")


# The token before the parameters: without it the answer is 401, whatever the query says.
router = APIRouter(dependencies=[Depends(_check_token)])
# Public: the vacancy buttons already sent to Telegram link to {webhook_url}/jobs/r/<id>.
public_router = APIRouter()


From = Annotated[str | None, Query(alias="from", description="Found at or after: 2026-10-01 or ISO date-time, UTC")]
To = Annotated[str | None, Query(description="Found before (exclusive); default now")]
_WORDS = "comma-separated whole words, case-insensitive"
AnyWords = Annotated[str | None, Query(alias="any", description=f"At least one of: {_WORDS}")]
AllWords = Annotated[str | None, Query(alias="all", description=f"Each of: {_WORDS}")]
NoWords = Annotated[str | None, Query(alias="none", description=f"None of: {_WORDS}")]
Where = Annotated[Literal["title", "description", "both"], Query(description="Where the words are looked for")]
Source = Annotated[str | None, Query(description="Comma-separated platforms: Djinni, Dou, Work.ua, ...")]
Company = Annotated[str | None, Query(description="Part of the company name, case-insensitive")]
Search = Annotated[str | None, Query(description="Part of the search URL that found the vacancy")]


def _csv(raw: str | None) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in (raw or "").split(",") if part.strip()))


def _filters(
    raw_from: str | None,
    raw_to: str | None,
    source: str | None,
    any_words: str | None,
    all_words: str | None,
    no_words: str | None,
    where: str,
    company: str | None,
    search: str | None,
) -> Filters:
    start, end = jobs_api.period(raw_from, raw_to)
    return Filters(
        start=start,
        end=end,
        sources=_csv(source),
        words=jobs_api.build_words(parse_words(any_words), parse_words(all_words), parse_words(no_words), where),
        company=company.strip() if company and company.strip() else None,
        search=search.strip() if search and search.strip() else None,
    )


async def _guarded(build: Any) -> Any:
    """The work; a bad parameter → 400, the DB down → 503, anything else a real 500."""
    try:
        return await build()
    except InvalidParameter as e:
        raise ApiError(400, "invalid_parameter", str(e)) from None
    except sql.UNAVAILABLE as e:
        logger.warning("Jobs API: storage unavailable: %s", e)
        raise ApiError(503, "storage_unavailable", "Job storage is unavailable; try again later") from None


# --- routes ------------------------------------------------------------------------------------


@router.get("", response_model=JobList, response_model_exclude_unset=True, responses=_ERRORS)
async def list_jobs(
    raw_from: From = None,
    to: To = None,
    status: Annotated[str | None, Query(description=f"Comma-separated: {', '.join(STATUSES)}")] = None,
    tier: Annotated[str | None, Query(description=f"Comma-separated: {', '.join(TIERS)}")] = None,
    source: Source = None,
    any_words: AnyWords = None,
    all_words: AllWords = None,
    no_words: NoWords = None,
    where: Where = "both",
    company: Company = None,
    url: Annotated[str | None, Query(description="A link to the vacancy, e.g. from an e-mail")] = None,
    source_id: Annotated[str | None, Query(description="The platform's own id of the vacancy")] = None,
    search: Search = None,
    filter_reason: Annotated[str | None, Query(description="Comma-separated: senior, experience, ...")] = None,
    reason_code: Annotated[str | None, Query(description="Comma-separated status_reason_code values")] = None,
    with_description: Annotated[bool, Query(description="Add each vacancy's full text")] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page")] = None,
) -> Any:
    """Vacancies, newest first; without their texts unless with_description=true."""

    async def build() -> dict[str, Any]:
        filters = _filters(raw_from, to, source, any_words, all_words, no_words, where, company, search)
        filters.statuses = jobs_api.parse_choice("status", status, STATUSES)
        filters.tiers = jobs_api.parse_choice("tier", tier, TIERS)
        filters.filter_reasons = _csv(filter_reason)
        filters.reason_codes = _csv(reason_code)
        filters.source_id = source_id.strip() if source_id and source_id.strip() else None
        if url:
            jobs_api.url_pattern(url)  # a bad link is a 400 before any query
            filters.url = url
        return await jobs_api.list_jobs(filters, limit, cursor, with_description)

    return await _guarded(build)


@router.get("/funnel", response_model=Funnel | EventFunnel, responses=_ERRORS)
async def funnel(
    raw_from: From = None,
    to: To = None,
    by: Annotated[
        Literal["found", "event"],
        Query(description="found: the vacancies found in the period; event: what happened in it (history)"),
    ] = "found",
    group_by: Annotated[str, Query(description=f"One of: {', '.join(GROUP_BY)}")] = "none",
    source: Source = None,
    any_words: AnyWords = None,
    all_words: AllWords = None,
    no_words: NoWords = None,
    where: Where = "both",
    company: Company = None,
    search: Search = None,
) -> Any:
    """Counts by stage: over the vacancies found in [from, to), or over the events in it."""

    async def build() -> dict[str, Any]:
        if group_by not in GROUP_BY:
            raise InvalidParameter(f"group_by: unknown value {group_by!r}; one of: {', '.join(GROUP_BY)}")
        filters = _filters(raw_from, to, source, any_words, all_words, no_words, where, company, search)
        if by == "event":
            body = await events.event_funnel(filters, group_by)
        else:
            body = {**await jobs_api.funnel(filters, group_by), "by": "found"}
        # The numbers do not wait for the journal. Without it the journal is null with
        # a reason, never []: an empty list would read as "the owner changed nothing".
        try:
            return {**body, "journal": await journal.entries(filters.start, filters.end), "journal_error": None}
        except sql.UNAVAILABLE as e:
            logger.warning("Funnel without the journal: SQL storage unavailable: %s", e)
            return {**body, "journal": None, "journal_error": "unavailable"}

    return await _guarded(build)


@router.post("/journal", response_model=JournalItem, status_code=201, responses=_ERRORS)
async def add_journal_entry(body: JournalPost) -> Any:
    """Note a change in the owner's approach: a new CV, another letter, a strategy."""

    async def build() -> dict[str, Any]:
        if body.kind not in journal.KINDS:
            raise InvalidParameter(f"kind: unknown value {body.kind!r}; one of: {', '.join(journal.KINDS)}")
        if body.actor not in journal.ACTORS:
            raise InvalidParameter(f"actor: {body.actor!r} is not allowed; one of: {', '.join(journal.ACTORS)}")
        text = body.text.strip()
        if not text or len(text) > journal.MAX_TEXT:
            raise InvalidParameter(f"text: from 1 to {journal.MAX_TEXT} characters")
        occurred_at = jobs_api.parse_time("occurred_at", body.occurred_at)
        if occurred_at is not None and occurred_at > datetime.utcnow() + status.CLOCK_SKEW:
            raise InvalidParameter(f"occurred_at: {body.occurred_at} is in the future")
        return await journal.add_entry(body.kind, text, body.actor, occurred_at)

    return await _guarded(build)


@router.get("/journal", response_model=JournalList, responses=_ERRORS)
async def journal_entries(raw_from: From = None, to: To = None) -> Any:
    """The owner's changes made in [from, to), oldest first; default the last 30 days."""

    async def build() -> dict[str, Any]:
        start, end = jobs_api.period(raw_from, to)
        return {"items": await journal.entries(start, end)}

    return await _guarded(build)


def _dates_to_utc(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _dates_to_utc(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dates_to_utc(item) for item in value]
    if isinstance(value, datetime):
        return jobs_api.utc(value)
    return value


@router.get("/digest", response_model=Digest, responses=_ERRORS)
async def digest(days: Annotated[int, Query(ge=1, le=180)] = 7) -> Any:
    """The numbers of the Friday digest in Telegram: the market, the owner's decisions, insights."""

    async def build() -> dict[str, Any]:
        data = await get_digest(days, strict=True)
        since, until = data.pop("since"), data.pop("until")
        return {"scope": jobs_api.SCOPE, **_dates_to_utc(data), "from": jobs_api.utc(since), "to": jobs_api.utc(until)}

    return await _guarded(build)


@router.get("/reasons", response_model=ReasonList, responses=_ERRORS)
async def reasons() -> Any:
    """The reason codes a client may set, per status, with what each one means."""
    return {"statuses": public_reasons()}


async def _write_status(job_id: str, body: StatusPatch) -> dict[str, Any]:
    """One status change → StatusResult; ApiError names what is wrong."""
    change = status.StatusChange(**body.model_dump(), given=set(body.model_fields_set))
    try:
        written = await status.patch_status(job_id, change)
    except InvalidParameter as e:
        raise ApiError(400, "invalid_parameter", str(e)) from None
    except status.JobNotFound:
        raise ApiError(404, "not_found", f"No vacancy with id {job_id!r}") from None
    except status.StatusConflict as e:
        message = f"expected_status: the status is {e.current_status!r} now; read it again and decide"
        raise ApiError(409, "status_conflict", message, current_status=e.current_status) from None
    except status.IsDuplicate as e:
        message = f"This vacancy is a repeat; its decision lives on {e.duplicate_of!r} — set the status there"
        raise ApiError(409, "is_duplicate", message, duplicate_of=e.duplicate_of) from None
    targets = await jobs_api.duplicate_targets([written.doc])
    copies = await jobs_api.group_copies([written.doc])
    return {
        "changed": written.changed,
        "job": jobs_api.job_full(written.doc, targets.get(job_id), copies.get(job_id)),
        "telegram": "queued" if written.queued else "skipped",
    }


@router.patch("/{job_id}/status", response_model=StatusResult, responses=_WRITE_ERRORS)
async def set_status(job_id: str, body: StatusPatch) -> Any:
    """Change the status; the vacancy's Telegram message follows right after."""

    async def build() -> dict[str, Any]:
        result = await _write_status(job_id, body)
        if result["telegram"] == "queued":
            kick_status_sync()
        return result

    return await _guarded(build)


MAX_BATCH = 25


class BatchItem(StatusPatch):
    job_id: str = Field(description="The vacancy's id")


class StatusBatch(BaseModel):
    """POST /jobs/status/batch: up to MAX_BATCH changes, each as in PATCH /jobs/{id}/status."""

    model_config = ConfigDict(extra="forbid")

    changes: list[BatchItem] = Field(min_length=1, max_length=MAX_BATCH)


class BatchResult(BaseModel):
    job_id: str
    ok: bool
    result: StatusResult | None = None
    error: dict[str, Any] | None = Field(default=None, description="As in an error response: code, message, ...")


class BatchResults(BaseModel):
    results: list[BatchResult] = Field(description="In the order of `changes`")
    written: int = Field(description="How many changed a status")
    failed: int


@router.post("/status/batch", response_model=BatchResults, responses=_ERRORS)
async def set_statuses(body: StatusBatch) -> Any:
    """Several status changes at once (16.11.2026): an AI sorting the inbox sends one call, and the
    owner gets one Telegram message. Each change stands alone — a conflict on one does not stop
    the rest; the storage going down does (503)."""

    async def build() -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for item in body.changes:
            patch = StatusPatch(**item.model_dump(exclude={"job_id"}, exclude_unset=True))
            try:
                results.append({"job_id": item.job_id, "ok": True, "result": await _write_status(item.job_id, patch)})
            except ApiError as e:
                error = {"code": e.code, "message": e.message, **e.extra}
                results.append({"job_id": item.job_id, "ok": False, "error": error})
        if any(r["ok"] and r["result"]["telegram"] == "queued" for r in results):
            kick_status_sync()
        written = sum(1 for r in results if r["ok"] and r["result"]["changed"])
        return {"results": results, "written": written, "failed": sum(1 for r in results if not r["ok"])}

    return await _guarded(build)


@router.get("/{job_id}", response_model=JobFull, responses=_ERRORS)
async def get_job(job_id: str) -> Any:
    """One vacancy with its full text."""

    async def build() -> dict[str, Any]:
        job = await jobs_api.get_job(job_id)
        if job is None:
            raise ApiError(404, "not_found", f"No vacancy with id {job_id!r}")
        return job

    return await _guarded(build)


@public_router.get("/r/{job_id}")
async def redirect_to_job(job_id: str) -> RedirectResponse:
    try:
        link = await jobs_api.open_link(job_id)
    except Exception as e:
        logger.warning("DB unavailable for job redirect: %s", e)
        raise HTTPException(status_code=503, detail="Job storage unavailable") from None
    if link is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return RedirectResponse(url=link, status_code=302)
