"""The Jobs API over the stored vacancies: list, one vacancy, the funnel.

The contract is docs/contracts/jobs-api.md. Its shape does not follow the storage: the
public `status` folds `user_status` and `outcome` into one stage, `tier` renames `moderation`,
dates go out as UTC with "Z", and no MongoDB name or operator leaks into a response.
"""

import base64
import binascii
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId

from src.config import settings
from src.db.client import jobs_collection
from src.services.job_searcher.dedup import BLOCKED, DECIDED, DUPLICATE, group_root
from src.services.job_searcher.digest import search_label
from src.services.job_searcher.words import MAX_WORD_LENGTH, MAX_WORDS, WHERE_FIELDS, case_free, words_query

SCOPE = "own_searches"
DEFAULT_PERIOD = timedelta(days=30)

# outcome (after "applied") → the public stage.
_OUTCOME_STATUS = {"reply": "replied", "interview": "interview", "offer": "offer", "rejected": "rejected_by_employer"}
STATUSES = (
    "new", "applied", "replied", "interview", "offer", "rejected_by_employer",
    "mismatch", "not_interested", "blocked", "duplicate",
)  # fmt: skip
TIERS = ("top", "sent", "review", "filtered_out")
SURFACED_TIERS = ("top", "sent", "review")
GROUP_BY = ("none", "source", "stack", "week", "tier", "search")
# How far an application got, in order; a refusal is an answer, so it reached "replied".
_STAGE_RANK = {"applied": 1, "replied": 2, "interview": 3, "offer": 4, "rejected_by_employer": 2}
_REACHED = ("applied", "replied", "interview", "offer")
# Statuses whose reason codes are the owner's (status_reason); the employer's come with part B.
_REASONED = ("mismatch", "not_interested")


class InvalidParameter(ValueError):
    """A query parameter the client got wrong; the message names it and says why."""


# --- one vacancy out ---------------------------------------------------------------------------


def utc(value: Any) -> str | None:
    """A stored date (naive UTC) as ISO 8601 with "Z"; text dates of old documents → None."""
    if not isinstance(value, datetime):
        return None
    moment: datetime = value
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment.isoformat(timespec="seconds") + "Z"


def public_status(doc: dict[str, Any]) -> str:
    user_status = doc.get("user_status") or "pending"
    if user_status == "pending":
        return "new"
    if user_status == "applied":
        return _OUTCOME_STATUS.get(doc.get("outcome") or "", "applied")
    return str(user_status)


def tier(doc: dict[str, Any]) -> str:
    moderation = doc.get("moderation")
    return moderation if moderation in SURFACED_TIERS else "filtered_out"


def stack(doc: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys((doc.get("matched_stack") or []) + (doc.get("matched_bonus") or [])))


def _status_changed_at(doc: dict[str, Any]) -> str | None:
    dates = [d for d in (doc.get("status_updated_at"), doc.get("outcome_at")) if isinstance(d, datetime)]
    return utc(max(dates)) if dates else None


def job_summary(doc: dict[str, Any], duplicate_of: str | None = None) -> dict[str, Any]:
    status = public_status(doc)
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title") or "",
        "company": doc.get("company"),
        "source": doc.get("platform_name") or "Unknown",
        "url": doc.get("link") or "",
        "found_at": utc(doc.get("found_at")),
        "published_at": utc(doc.get("date")),
        "status": status,
        "status_reason_code": doc.get("status_reason") if status in _REASONED else None,
        "status_reason": None,  # the free text arrives with part B
        "status_changed_at": _status_changed_at(doc),
        "tier": tier(doc),
        "filter_reason": doc.get("filter_reason"),
        "stack": stack(doc),
        "work_format": doc.get("work_format"),
        "english": doc.get("english"),
        "required_years": doc.get("required_years"),
        "salary": doc.get("salary"),
        "search": doc.get("search_url"),
        "duplicate_of": duplicate_of if status == "duplicate" else None,
    }


def job_full(doc: dict[str, Any], duplicate_of: str | None = None) -> dict[str, Any]:
    return {
        **job_summary(doc, duplicate_of),
        "description": doc.get("description") or "",
        "location": doc.get("location"),
        "countries": doc.get("countries"),
        "applicants": doc.get("applicants"),
        "warnings": list(doc.get("warnings") or []),
        "copies": [
            {"id": copy["id"], "source": copy.get("platform") or "Unknown"}
            for copy in doc.get("copies") or []
            if copy.get("id")
        ],
    }


async def duplicate_targets(docs: list[dict[str, Any]]) -> dict[str, str]:
    """For each repeat among `docs`: the id of the copy its group's decision lives on.

    The decided copy if there is one, else a pending one (the owner can still answer there),
    else a blocked one, the oldest first; with none of them, the group's root. One query per page.
    """
    roots = {group_root(doc) for doc in docs if doc.get("user_status") == DUPLICATE}
    if not roots:
        return {}
    object_ids = [ObjectId(root) for root in roots if ObjectId.is_valid(root)]
    query = {
        "$or": [{"_id": {"$in": object_ids}}, {"group_id": {"$in": list(roots)}}],
        "user_status": {"$ne": DUPLICATE},
    }
    best: dict[str, tuple[int, ObjectId]] = {}
    async for copy in jobs_collection.find(query, {"_id": 1, "group_id": 1, "user_status": 1}):
        status = copy.get("user_status")
        rank = 0 if status in DECIDED else 2 if status == BLOCKED else 1
        root = group_root(copy)
        if root not in best or (rank, copy["_id"]) < best[root]:
            best[root] = (rank, copy["_id"])
    return {
        str(doc["_id"]): str(best[root][1]) if (root := group_root(doc)) in best else root
        for doc in docs
        if doc.get("user_status") == DUPLICATE
    }


# --- parameters --------------------------------------------------------------------------------


def parse_time(name: str, raw: str | None) -> datetime | None:
    """ "2026-10-01" or an ISO date-time (with or without zone, read as UTC) → naive UTC."""
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        raise InvalidParameter(f"{name}: {raw!r} is not a date (2026-10-01) or ISO date-time") from None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def period(raw_from: str | None, raw_to: str | None) -> tuple[datetime, datetime]:
    end = parse_time("to", raw_to) or datetime.utcnow()
    start = parse_time("from", raw_from) or end - DEFAULT_PERIOD
    if start >= end:
        raise InvalidParameter(f"from: {utc(start)} is not earlier than to: {utc(end)}")
    return start, end


def parse_choice(name: str, raw: str | None, allowed: tuple[str, ...]) -> list[str]:
    values = [part.strip().lower() for part in (raw or "").split(",") if part.strip()]
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise InvalidParameter(f"{name}: unknown value {unknown[0]!r}; one of: {', '.join(allowed)}")
    return list(dict.fromkeys(values))


def _status_condition(status: str) -> dict[str, Any]:
    if status == "new":
        return {"user_status": {"$in": ["pending", None]}}
    if status == "applied":
        return {"user_status": "applied", "outcome": None}
    outcome = next((key for key, value in _OUTCOME_STATUS.items() if value == status), None)
    if outcome:
        return {"user_status": "applied", "outcome": outcome}
    return {"user_status": status}


def _tier_condition(tiers: list[str]) -> dict[str, Any]:
    moderation: list[str | None] = [t for t in tiers if t in SURFACED_TIERS]
    if "filtered_out" in tiers:
        moderation += ["rejected_by_filter", None]
    return {"moderation": {"$in": moderation}}


def url_pattern(raw: str) -> str:
    """A vacancy link as the client has it (from an e-mail) → a regex for the stored link.

    The host is compared without "www." and the case, the path without a trailing "/", and the
    query and the fragment are ignored: trackers add them, the boards' own links rarely have any.
    """
    try:
        parsed = urlparse(raw.strip() if "://" in raw else f"https://{raw.strip()}")
    except ValueError:  # "http://[abc": a broken IPv6 host
        raise InvalidParameter(f"url: {raw!r} is not a link to a vacancy") from None
    host = (parsed.hostname or "").removeprefix("www.")
    if not host or "." not in host:
        raise InvalidParameter(f"url: {raw!r} is not a link to a vacancy")
    path = re.escape(parsed.path.rstrip("/"))
    return f"^https?://(www\\.)?{case_free(host)}(:\\d+)?{path}/?([?#].*)?$"


@dataclass
class Filters:
    """What the list and the funnel narrow the vacancies by; built from the query string."""

    start: datetime
    end: datetime
    statuses: list[str] = field(default_factory=list)
    tiers: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    words: list[dict[str, Any]] = field(default_factory=list)
    company: str | None = None
    url: str | None = None
    search: str | None = None
    source_id: str | None = None
    filter_reasons: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def query(self, *, default_tiers: bool = True, repeats: bool = False) -> dict[str, Any]:
        conditions: list[dict[str, Any]] = [{"found_at": {"$gte": self.start, "$lt": self.end}}]
        if self.statuses:
            conditions.append({"$or": [_status_condition(status) for status in self.statuses]})
        elif not repeats:
            conditions.append({"user_status": {"$ne": DUPLICATE}})
        if self.tiers:
            conditions.append(_tier_condition(self.tiers))
        elif default_tiers and not self.filter_reasons:  # a filter reason is only on the filtered-out
            conditions.append(_tier_condition(list(SURFACED_TIERS)))
        if self.sources:
            names = [re.compile(f"^{re.escape(source)}$", re.IGNORECASE) for source in self.sources]
            conditions.append({"platform_name": {"$in": names}})
        if self.company:
            conditions.append({"company": {"$regex": case_free(self.company)}})
        if self.url:
            conditions.append({"link": {"$regex": url_pattern(self.url)}})
        if self.search:
            conditions.append({"search_url": {"$regex": case_free(self.search)}})
        if self.source_id:
            conditions.append({"job_id": self.source_id})
        if self.filter_reasons:
            conditions.append({"filter_reason": {"$in": self.filter_reasons}})
        if self.reason_codes:
            conditions.append({"status_reason": {"$in": self.reason_codes}})
        conditions += self.words
        return {"$and": conditions}


def build_words(any_words: list[str], all_words: list[str], no_words: list[str], where: str) -> list[dict[str, Any]]:
    if where not in WHERE_FIELDS:
        raise InvalidParameter(f"where: unknown value {where!r}; one of: {', '.join(WHERE_FIELDS)}")
    for name, words in (("any", any_words), ("all", all_words), ("none", no_words)):
        if len(words) > MAX_WORDS:
            raise InvalidParameter(f"{name}: {len(words)} words, at most {MAX_WORDS}")
        if long := next((word for word in words if len(word) > MAX_WORD_LENGTH), None):
            raise InvalidParameter(f"{name}: {long[:20]!r}… is longer than {MAX_WORD_LENGTH} characters")
    return words_query(any_words, all_words, no_words, where)


# --- the list ----------------------------------------------------------------------------------


def encode_cursor(doc: dict[str, Any]) -> str:
    payload = json.dumps({"f": doc["found_at"].isoformat(), "i": str(doc["_id"])}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(raw: str) -> tuple[datetime, ObjectId]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return datetime.fromisoformat(payload["f"]), ObjectId(payload["i"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError, InvalidId):
        raise InvalidParameter("cursor: not a next_cursor this API returned; start without it") from None


def after_cursor(query: dict[str, Any], cursor: str | None) -> dict[str, Any]:
    """Keyset paging, newest first: only what sorts after the last vacancy of the previous page.

    Vacancies found while the client pages sort before the cursor, so they never shift a page.
    """
    if not cursor:
        return query
    found_at, object_id = decode_cursor(cursor)
    older = {"$or": [{"found_at": {"$lt": found_at}}, {"found_at": found_at, "_id": {"$lt": object_id}}]}
    return {"$and": [query, older]}


LIST_SORT = [("found_at", -1), ("_id", -1)]


async def list_jobs(filters: Filters, limit: int, cursor: str | None, with_description: bool = False) -> dict[str, Any]:
    query = after_cursor(filters.query(), cursor)
    projection = None if with_description else {"description": 0}
    found = jobs_collection.find(query, projection).sort(LIST_SORT).limit(limit + 1)
    docs = [doc async for doc in found]
    page, more = docs[:limit], len(docs) > limit
    targets = await duplicate_targets(page)

    def item(doc: dict[str, Any]) -> dict[str, Any]:
        summary = job_summary(doc, targets.get(str(doc["_id"])))
        return {**summary, "description": doc.get("description") or ""} if with_description else summary

    return {
        "scope": SCOPE,
        "items": [item(doc) for doc in page],
        "next_cursor": encode_cursor(page[-1]) if more and page else None,
    }


async def get_job(job_id: str) -> dict[str, Any] | None:
    if not ObjectId.is_valid(job_id):
        return None
    doc = await jobs_collection.find_one({"_id": ObjectId(job_id)})
    if doc is None:
        return None
    targets = await duplicate_targets([doc])
    return job_full(doc, targets.get(job_id))


# --- the funnel --------------------------------------------------------------------------------

UNKNOWN_SEARCH = "(unknown)"  # vacancies stored before 06.10.2026 keep no search


def _empty_group(key: str, label: str | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label or key,
        "found": 0, "repeats": 0, "filtered_out": 0, "surfaced": 0,
        "tiers": dict.fromkeys(TIERS, 0),
        "decided": 0, "new": 0, "opened": 0, "clicks": 0,
        "reached": dict.fromkeys(_REACHED, 0),
        "status": {status: 0 for status in STATUSES if status != "duplicate"},
        "rejected_after": {"applied": 0, "replied": 0, "interview": 0, "unknown": 0},
        "reasons": {"rejected_by_employer": {}, "mismatch": {}, "not_interested": {}, "filtered_out": {}},
        "apply_rate": None, "reply_rate": None, "median_hours_to_decision": None,
        "_hours": [],
    }  # fmt: skip


def _count(group: dict[str, Any], doc: dict[str, Any]) -> None:
    if doc.get("user_status") == DUPLICATE:
        group["repeats"] += 1  # counted apart: one vacancy, one decision
        return
    group["found"] += 1
    group["tiers"][tier(doc)] += 1
    if tier(doc) == "filtered_out":
        group["filtered_out"] += 1
        reasons = group["reasons"]["filtered_out"]
        reason = doc.get("filter_reason") or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
        return
    group["surfaced"] += 1
    clicks = int(doc.get("click_count") or 0)
    group["clicks"] += clicks
    group["opened"] += clicks > 0
    status = public_status(doc)
    group["status"][status] = group["status"].get(status, 0) + 1
    group["new" if status == "new" else "decided"] += 1
    rank = _STAGE_RANK.get(status, 0)
    for stage in _REACHED:
        group["reached"][stage] += rank >= _STAGE_RANK[stage]
    if status == "rejected_by_employer":
        group["rejected_after"]["unknown"] += 1  # the stage is known only from part B's history
    if status in _REASONED and (code := doc.get("status_reason")):
        reasons = group["reasons"][status]
        reasons[code] = reasons.get(code, 0) + 1
    decided_at, found_at = doc.get("status_updated_at"), doc.get("found_at")
    if not (status != "new" and isinstance(decided_at, datetime) and isinstance(found_at, datetime)):
        return
    if decided_at >= found_at:
        group["_hours"].append((decided_at - found_at).total_seconds() / 3600)


def _finish(group: dict[str, Any]) -> dict[str, Any]:
    group["reasons"] = {name: dict(Counter(counts).most_common()) for name, counts in group["reasons"].items()}
    reached, hours = group["reached"], group.pop("_hours")
    group["apply_rate"] = round(reached["applied"] / group["decided"], 3) if group["decided"] else None
    group["reply_rate"] = round(reached["replied"] / reached["applied"], 3) if reached["applied"] else None
    group["median_hours_to_decision"] = round(median(hours), 1) if hours else None
    return group


def _keys(doc: dict[str, Any], group_by: str) -> list[str]:
    if group_by == "source":
        return [doc.get("platform_name") or "Unknown"]
    if group_by == "tier":
        return [tier(doc)]
    if group_by == "stack":
        return stack(doc) or ["(none)"]
    if group_by == "search":
        return [doc.get("search_url") or UNKNOWN_SEARCH]
    if group_by == "week":
        found_at = doc["found_at"].replace(tzinfo=UTC).astimezone(ZoneInfo(settings.tz))
        year, week, _ = found_at.isocalendar()
        return [f"{year}-W{week:02d}"]
    return ["all"]


def _label(key: str, group_by: str) -> str:
    return search_label(key) if group_by == "search" and key != UNKNOWN_SEARCH else key


def funnel_groups(docs: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for doc in docs:
        for key in _keys(doc, group_by):
            _count(groups.setdefault(key, _empty_group(key, _label(key, group_by))), doc)
    finished = [_finish(group) for group in groups.values()]
    if group_by == "week":
        return sorted(finished, key=lambda group: group["key"])
    return sorted(finished, key=lambda group: (-group["found"], group["key"]))


async def funnel(filters: Filters, group_by: str) -> dict[str, Any]:
    # Every tier: the funnel reports what the filter dropped too. Repeats are only counted.
    query = filters.query(default_tiers=False, repeats=True)
    docs = [doc async for doc in jobs_collection.find(query, {"description": 0})]
    # An empty period is a real answer: zeros, not an empty list, when nothing is grouped.
    groups = funnel_groups(docs, group_by) or ([_finish(_empty_group("all"))] if group_by == "none" else [])
    return {
        "scope": SCOPE,
        "from": utc(filters.start),
        "to": utc(filters.end),
        "group_by": group_by,
        "groups": groups,
    }
