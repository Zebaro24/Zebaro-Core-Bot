"""The weekly digest: what the market asks for, and how the owner's search went.

Two parts, two messages (06.10.2026):

* market — the vacancies in his field found this period (not those built on another stack,
  not a non-developer role): what experience, English, work format and technologies they ask
  for, what they pay, and what keeps him out of them;
* me — his decisions this period (counted by the moment he pressed the button, not when the
  vacancy was found, or late answers fall out of every week): the answers and their trend,
  conversion per site, tier and search, why he could not apply, what waits unanswered.

Every share is computed here; the formatter only lays it out. A figure with too little behind
it is None and is not shown — with ~100 decisions a week, a percentage over four is noise.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.db.client import jobs_collection
from src.services.job_searcher.extract import english_rank

logger = logging.getLogger("job_searcher.digest")

SURFACED = ("top", "sent", "review")
# Not his field: these say nothing about what *his* market wants.
_OUTSIDE_FIELD = ("other stack", "not a developer role", "military", "company", "location")
DECISIONS = ("applied", "mismatch", "not_interested", "blocked")

# Searches are compared over four weeks: one week gives a search 1-5 answers.
SEARCH_WINDOW_DAYS = 28
MIN_SEARCH_DECISIONS = 8
MIN_SALARIES = 5
MIN_FOR_SHARE = 5
TOP_TECH = 8
PENDING_OLD_DAYS = 3


async def _find(query: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return [doc async for doc in jobs_collection.find(query, {"description": 0})]
    except Exception as e:
        logger.warning("DB unavailable for the digest: %s", e)
        return []


async def get_digest(days: int = 7) -> dict[str, Any]:
    now = datetime.utcnow()
    since, before = now - timedelta(days=days), now - timedelta(days=2 * days)
    found = await _find({"found_at": {"$gte": since}, "user_status": {"$ne": "duplicate"}})
    decided = await _find({"status_updated_at": {"$gte": before}, "user_status": {"$in": list(DECISIONS)}})
    window = await _find(
        {
            "status_updated_at": {"$gte": now - timedelta(days=max(days, SEARCH_WINDOW_DAYS))},
            "user_status": {"$in": list(DECISIONS)},
        }
    )
    pending = await _find(
        {"moderation": {"$in": list(SURFACED)}, "user_status": "pending", "found_at": {"$gte": since}}
    )
    this_week = [doc for doc in decided if doc["status_updated_at"] >= since]
    last_week = [doc for doc in decided if doc["status_updated_at"] < since]
    return {
        "period_days": days,
        "market": market_stats(found),
        "me": my_stats(this_week, last_week, window, pending, now),
        "silent_sources": _silent(found),
    }


def _silent(found: list[dict[str, Any]]) -> list[str]:
    from src.services.job_searcher.stats import silent_sources

    by_platform: dict[str, dict[str, int]] = {}
    for doc in found:
        by_platform.setdefault(doc.get("platform_name") or "Unknown", {"found": 0})["found"] += 1
    return silent_sources(by_platform) if found else []


# --- market --------------------------------------------------------------------------------


def _years_bucket(years: int | None) -> str:
    if years is None:
        return "?"
    return "≤1" if years <= 1 else "4+" if years >= 4 else str(years)


def _english_bucket(level: str | None) -> str:
    rank = english_rank(level)
    if rank is None:
        return "?"
    return "≤B1" if rank <= english_rank("B1") else "B2" if level == "B2" else "C1+"  # type: ignore[operator]


_MONEY = re.compile(r"\d[\d\s]*")


def salary_value(text: str | None) -> int | None:
    """ "$3500–4500" → 4000, "до $2500" → 2500, "від $3000" → 3000; None without dollars."""
    if not text or "$" not in text:
        return None
    numbers = [int(re.sub(r"\s", "", match)) for match in _MONEY.findall(text)]
    numbers = [number for number in numbers if 100 <= number <= 50_000]
    return round(sum(numbers) / len(numbers)) if numbers else None


def _share(counter: Counter, total: int) -> list[tuple[str, float]]:
    return [(name, count / total) for name, count in counter.most_common()] if total else []


def market_stats(found: list[dict[str, Any]]) -> dict[str, Any]:
    field = [doc for doc in found if doc.get("filter_reason") not in _OUTSIDE_FIELD]
    surfaced = [doc for doc in field if doc.get("moderation") in SURFACED]
    years = Counter(_years_bucket(doc.get("required_years")) for doc in field)
    english = Counter(_english_bucket(doc.get("english")) for doc in field)
    formats = Counter(doc.get("work_format") for doc in field if doc.get("work_format"))
    tech = Counter(
        name for doc in surfaced for name in (doc.get("matched_stack") or []) + (doc.get("matched_bonus") or [])
    )
    salaries = [value for doc in field if (value := salary_value(doc.get("salary"))) is not None]
    applicants = [doc["applicants"] for doc in surfaced if isinstance(doc.get("applicants"), int)]
    # Why the vacancies of his field are not for him: the filter's reasons, his limits first.
    blockers = Counter(doc.get("filter_reason") for doc in field if doc.get("moderation") == "rejected_by_filter")
    blockers.pop("no stack match", None)
    blockers.pop(None, None)
    known_english = sum(count for bucket, count in english.items() if bucket != "?")
    return {
        "in_field": len(field),
        "surfaced": len(surfaced),
        "by_tier": {tier: sum(doc.get("moderation") == tier for doc in surfaced) for tier in SURFACED},
        "years": {bucket: years.get(bucket, 0) for bucket in ("≤1", "2", "3", "4+", "?")},
        "english": {bucket: english.get(bucket, 0) for bucket in ("≤B1", "B2", "C1+", "?")},
        # Of the vacancies that name a level, how many his B1 passes without a question.
        "english_b1_share": english.get("≤B1", 0) / known_english if known_english >= MIN_FOR_SHARE else None,
        "work_format": dict(formats.most_common()),
        "top_tech": [(name, count / len(surfaced)) for name, count in tech.most_common(TOP_TECH)] if surfaced else [],
        "salary": (
            {"median": round(median(salaries)), "low": min(salaries), "high": max(salaries), "n": len(salaries)}
            if len(salaries) >= MIN_SALARIES
            else None
        ),
        "applicants_median": round(median(applicants)) if len(applicants) >= MIN_FOR_SHARE else None,
        "blockers": dict(blockers.most_common()),
    }


# --- me ------------------------------------------------------------------------------------


_SITES = {
    "jobs.dou.ua": "DOU", "djinni.co": "Djinni", "www.work.ua": "Work.ua", "robota.ua": "Robota.ua",
    "nofluffjobs.com": "No Fluff Jobs", "happymonday.ua": "HappyMonday", "app.bazait.com": "BazaIT",
    "wellfound.com": "Wellfound",
}  # fmt: skip
_PATH_NOISE = ("jobs", "vacancies", "zapros", "role", "l", "jobs-search", "search", "ua-ru", "viddalena-robota")


def search_label(url: str | None) -> str:
    """A search URL in a few words: "Djinni · python", "DOU · Fullstack remote"."""
    if not url:
        return "?"
    parsed = urlparse(url)
    site = _SITES.get(parsed.netloc, parsed.netloc)
    query = parse_qs(parsed.query, keep_blank_values=True)
    words: list[str] = []
    for key in ("category", "all_keywords", "any_of_keywords", "primary_keyword", "criteria"):
        words += query.get(key, [])
    words += [key for key in ("remote", "relocation") if key in query]
    path = [part for part in parsed.path.split("/") if part and part not in _PATH_NOISE and ";" not in part]
    if not words:
        words = [part.removeprefix("keyword-").replace("jobs-remote-", "remote ") for part in path[:2]]
    text = " ".join(words).replace("jobPosition=", "").replace("'", "").replace("+", " ")
    return f"{site} · {text}".strip(" ·")


def _rate(docs: list[dict[str, Any]]) -> float | None:
    return sum(doc.get("user_status") == "applied" for doc in docs) / len(docs) if docs else None


def _counts(docs: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(doc.get("user_status") for doc in docs)
    return {status: counter.get(status, 0) for status in DECISIONS}


def my_stats(
    this_week: list[dict[str, Any]],
    last_week: list[dict[str, Any]],
    window: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for doc in this_week:
        by_platform.setdefault(doc.get("platform_name") or "?", []).append(doc)
    platforms = [
        {"platform": name, "decided": len(docs), "applied": _counts(docs)["applied"], "rate": _rate(docs),
         "blocked": _counts(docs)["blocked"]}
        for name, docs in sorted(by_platform.items(), key=lambda item: -len(item[1]))
    ]  # fmt: skip

    by_search: dict[str, list[dict[str, Any]]] = {}
    for doc in window:
        if doc.get("search_url"):
            by_search.setdefault(search_label(doc["search_url"]), []).append(doc)
    searches: list[dict[str, Any]] = [
        {"label": label, "n": len(docs), "rate": _rate(docs) or 0.0}
        for label, docs in by_search.items()
        if len(docs) >= MIN_SEARCH_DECISIONS
    ]
    searches.sort(key=lambda item: -float(item["rate"]))

    by_tier = {
        tier: _rate(docs) if len(docs := [doc for doc in window if doc.get("moderation") == tier]) >= MIN_FOR_SHARE
        else None
        for tier in SURFACED
    }  # fmt: skip
    mismatch = [doc for doc in this_week if doc.get("user_status") in ("mismatch", "blocked")]
    mismatch_reasons = Counter(
        "site" if doc.get("user_status") == "blocked" else doc.get("status_reason") or "other" for doc in mismatch
    )
    rejected = [doc for doc in this_week if doc.get("user_status") == "not_interested"]
    mismatch_years = [doc["required_years"] for doc in mismatch if isinstance(doc.get("required_years"), int)]
    # The filter promised a fit and he could not apply: a rule to fix.
    promised = [doc for doc in this_week if doc.get("moderation") in ("top", "sent")]
    promised_mismatch = [doc for doc in promised if doc.get("user_status") in ("mismatch", "blocked")]
    old = [doc for doc in pending if (now - doc["found_at"]).days >= PENDING_OLD_DAYS]
    hours = [
        (doc["status_updated_at"] - doc["found_at"]).total_seconds() / 3600
        for doc in this_week
        if doc.get("found_at") and doc["status_updated_at"] >= doc["found_at"]
    ]
    return {
        "decisions": _counts(this_week),
        "prev": _counts(last_week),
        "apply_rate": _rate(this_week),
        "apply_rate_prev": _rate(last_week),
        "pending": {"count": len(pending), "old": len(old)},
        "by_platform": platforms,
        "by_tier_rate": by_tier,
        "searches": (
            {"best": searches[:3], "worst": searches[max(3, len(searches) - 3) :][::-1]} if len(searches) >= 2 else None
        ),
        "mismatch_reasons": dict(mismatch_reasons.most_common()),
        "mismatch_years_median": round(median(mismatch_years)) if mismatch_years else None,
        "not_interested_reasons": dict(Counter(doc.get("status_reason") or "other" for doc in rejected).most_common()),
        "filter_misses": {"mismatch": len(promised_mismatch), "promised": len(promised)} if promised else None,
        "avg_hours_to_action": sum(hours) / len(hours) if hours else None,
    }
