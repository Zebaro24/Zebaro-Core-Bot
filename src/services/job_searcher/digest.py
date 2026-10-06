"""The weekly digest: who the companies are looking for, and how the owner's search went.

Two parts, two messages (06.10.2026):

* market — the vacancies in his field found this period (not those built on another stack,
  not a non-developer role): what experience, English, work format and technologies they ask
  for, what they pay, how many apply, what keeps him out — and how that moved since last week;
* me — his decisions this period (counted by the moment he pressed the button, not when the
  vacancy was found, or late answers fall out of every week): the funnel from found to
  applied, the answers and their trend, conversion per site, tier and search, what he lacks.

Both end in insights: the few conclusions worth acting on, picked by rules over the numbers
(`market_insights`, `my_insights`). They are data — a kind and its figures; the formatter
words them. Every share is computed here; a figure with too little behind it is None and is
not shown — with ~100 decisions a week, a percentage over four answers is noise.
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
# Why a vacancy of his field is out of reach — his limits, as the filter names them.
_REACH_REASONS = ("senior", "experience", "lead", "english", "office", "country")

# The owner's own figures, for "where you stand" marks (06.10.2026).
OWNER_YEARS_BUCKET = "3"
OWNER_ENGLISH_BUCKET = "≤B1"

# Searches are compared over four weeks: one week gives a search 1-5 answers.
SEARCH_WINDOW_DAYS = 28
MIN_SEARCH_DECISIONS = 8
MIN_SALARIES = 5
MIN_FOR_SHARE = 5
TOP_TECH = 8
PENDING_OLD_DAYS = 3
# A tech share has to move by this much week to week to count as a trend, not noise.
TREND_POINTS = 0.08
# Insights shown at most: the point is the few that matter.
MAX_INSIGHTS = 5


async def _find(query: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return [doc async for doc in jobs_collection.find(query, {"description": 0})]
    except Exception as e:
        logger.warning("DB unavailable for the digest: %s", e)
        return []


async def get_digest(days: int = 7) -> dict[str, Any]:
    now = datetime.utcnow()
    since, before = now - timedelta(days=days), now - timedelta(days=2 * days)
    found_both = await _find({"found_at": {"$gte": before}, "user_status": {"$ne": "duplicate"}})
    found = [doc for doc in found_both if doc["found_at"] >= since]
    found_prev = [doc for doc in found_both if doc["found_at"] < since]
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
    market = market_stats(found, found_prev)
    me = my_stats(this_week, last_week, window, pending, now, found)
    return {
        "period_days": days,
        "since": since,
        "until": now,
        "market": market,
        "me": me,
        "market_insights": market_insights(market),
        "my_insights": my_insights(me, market),
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
    return "≤B1" if rank <= (english_rank("B1") or 0) else "B2" if level == "B2" else "C1+"


_MONEY = re.compile(r"\d[\d\s]*")


def salary_value(text: str | None) -> int | None:
    """ "$3500–4500" → 4000, "до $2500" → 2500, "від $3000" → 3000; None without dollars."""
    if not text or "$" not in text:
        return None
    numbers = [int(re.sub(r"\s", "", match)) for match in _MONEY.findall(text)]
    numbers = [number for number in numbers if 100 <= number <= 50_000]
    return round(sum(numbers) / len(numbers)) if numbers else None


def _field(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [doc for doc in found if doc.get("filter_reason") not in _OUTSIDE_FIELD]


def _tech_shares(surfaced: list[dict[str, Any]]) -> dict[str, float]:
    if not surfaced:
        return {}
    tech = Counter(
        name for doc in surfaced for name in (doc.get("matched_stack") or []) + (doc.get("matched_bonus") or [])
    )
    return {name: count / len(surfaced) for name, count in tech.most_common()}


def _known_share(counter: Counter, bucket: str) -> float | None:
    known = sum(count for name, count in counter.items() if name != "?")
    return counter.get(bucket, 0) / known if known >= MIN_FOR_SHARE else None


def market_stats(found: list[dict[str, Any]], found_prev: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    field = _field(found)
    surfaced = [doc for doc in field if doc.get("moderation") in SURFACED]
    prev_field = _field(found_prev or [])
    prev_surfaced = [doc for doc in prev_field if doc.get("moderation") in SURFACED]

    years = Counter(_years_bucket(doc.get("required_years")) for doc in field)
    english = Counter(_english_bucket(doc.get("english")) for doc in field)
    formats = Counter(doc.get("work_format") for doc in field if doc.get("work_format"))
    shares, prev_shares = _tech_shares(surfaced), _tech_shares(prev_surfaced)
    salaries = sorted(value for doc in field if (value := salary_value(doc.get("salary"))) is not None)
    applicants = [doc["applicants"] for doc in surfaced if isinstance(doc.get("applicants"), int)]
    blockers = Counter(doc.get("filter_reason") for doc in field if doc.get("moderation") == "rejected_by_filter")
    known_english = sum(count for bucket, count in english.items() if bucket != "?")
    known_years = sum(count for bucket, count in years.items() if bucket != "?")
    return {
        "in_field": len(field),
        "in_field_prev": len(prev_field) if found_prev is not None else None,
        "surfaced": len(surfaced),
        "surfaced_prev": len(prev_surfaced) if found_prev is not None else None,
        "reach_share": len(surfaced) / len(field) if field else None,
        "by_tier": {tier: sum(doc.get("moderation") == tier for doc in surfaced) for tier in SURFACED},
        "years": {bucket: years.get(bucket, 0) for bucket in ("≤1", "2", "3", "4+", "?")},
        "years_known": known_years,
        "years_over_share": _known_share(years, "4+"),
        "english": {bucket: english.get(bucket, 0) for bucket in ("≤B1", "B2", "C1+", "?")},
        "english_known": known_english,
        # Of the vacancies that name a level, how many his B1 passes without a question.
        "english_b1_share": _known_share(english, "≤B1"),
        "english_b2_count": english.get("B2", 0),
        "work_format": dict(formats.most_common()),
        "top_tech": [
            # No last week at all: no trend. Absent last week: it came from nothing.
            {"name": name, "share": share, "delta": share - prev_shares.get(name, 0.0) if prev_shares else None}
            for name, share in list(shares.items())[:TOP_TECH]
        ],
        "salary": (
            {
                "median": round(median(salaries)),
                "low": salaries[len(salaries) // 4],
                "high": salaries[(3 * len(salaries)) // 4],
                "n": len(salaries),
            }
            if len(salaries) >= MIN_SALARIES
            else None
        ),
        "applicants": (
            {"median": round(median(applicants)), "max": max(applicants), "n": len(applicants)}
            if len(applicants) >= MIN_FOR_SHARE
            else None
        ),
        "blockers": {reason: blockers[reason] for reason in _REACH_REASONS if blockers.get(reason)},
    }


def market_insights(market: dict[str, Any]) -> list[dict[str, Any]]:
    """What the market numbers say, most important first."""
    insights: list[dict[str, Any]] = []
    blockers = market["blockers"]
    seniority = blockers.get("senior", 0) + blockers.get("experience", 0) + blockers.get("lead", 0)
    if market["in_field"] and seniority / market["in_field"] >= 0.25:
        insights.append({"kind": "seniority_wall", "count": seniority, "share": seniority / market["in_field"]})
    if market["english_b1_share"] is not None and market["english_b2_count"]:
        insights.append(
            {"kind": "english_gate", "b1_share": market["english_b1_share"], "b2_count": market["english_b2_count"]}
        )
    rising = [tech for tech in market["top_tech"] if tech["delta"] is not None and tech["delta"] >= TREND_POINTS]
    falling = [tech for tech in market["top_tech"] if tech["delta"] is not None and tech["delta"] <= -TREND_POINTS]
    if rising:
        insights.append({"kind": "tech_rising", "names": [tech["name"] for tech in rising[:3]]})
    if falling:
        insights.append({"kind": "tech_falling", "names": [tech["name"] for tech in falling[:3]]})
    if market["in_field_prev"]:
        change = market["in_field"] / market["in_field_prev"] - 1
        if abs(change) >= 0.2:
            insights.append({"kind": "volume", "change": change, "now": market["in_field"]})
    if market["applicants"] and market["applicants"]["median"] >= 100:
        insights.append({"kind": "competition", "median": market["applicants"]["median"]})
    return insights[:MAX_INSIGHTS]


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


def _funnel(found: list[dict[str, Any]]) -> dict[str, int]:
    """Of this week's vacancies: found, sent to the chat, opened by the link, applied to."""
    surfaced = [doc for doc in found if doc.get("moderation") in SURFACED]
    return {
        "found": len(found),
        "surfaced": len(surfaced),
        "opened": sum(int(doc.get("click_count") or 0) > 0 for doc in surfaced),
        "applied": sum(doc.get("user_status") == "applied" for doc in surfaced),
    }


def my_stats(
    this_week: list[dict[str, Any]],
    last_week: list[dict[str, Any]],
    window: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    now: datetime,
    found: list[dict[str, Any]] | None = None,
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
    promised_reasons = Counter(
        "site" if doc.get("user_status") == "blocked" else doc.get("status_reason") or "other"
        for doc in promised_mismatch
    )
    old = [doc for doc in pending if (now - doc["found_at"]).days >= PENDING_OLD_DAYS]
    hours = [
        (doc["status_updated_at"] - doc["found_at"]).total_seconds() / 3600
        for doc in this_week
        if doc.get("found_at") and doc["status_updated_at"] >= doc["found_at"]
    ]
    applied = [doc for doc in window if doc.get("user_status") == "applied"]
    return {
        "decisions": _counts(this_week),
        "prev": _counts(last_week),
        "apply_rate": _rate(this_week),
        "apply_rate_prev": _rate(last_week),
        "funnel": _funnel(found or []),
        "pending": {"count": len(pending), "old": len(old)},
        "by_platform": platforms,
        "by_tier_rate": by_tier,
        "searches": _best_and_worst(searches),
        "dead_searches": [s["label"] for s in searches if s["rate"] == 0.0],
        "mismatch_reasons": dict(mismatch_reasons.most_common()),
        "mismatch_years_median": round(median(mismatch_years)) if mismatch_years else None,
        "not_interested_reasons": dict(Counter(doc.get("status_reason") or "other" for doc in rejected).most_common()),
        "filter_misses": (
            {"mismatch": len(promised_mismatch), "promised": len(promised), "reasons": dict(promised_reasons)}
            if promised
            else None
        ),
        "avg_hours_to_action": median(hours) if hours else None,
        # What the vacancies he applies to have in common (four weeks): his real profile.
        "applied_tech": [
            {"name": name, "share": count / len(applied)}
            for name, count in Counter(
                name for doc in applied for name in (doc.get("matched_stack") or []) + (doc.get("matched_bonus") or [])
            ).most_common(5)
        ]
        if len(applied) >= MIN_FOR_SHARE
        else [],
    }


def _best_and_worst(searches: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]] | None:
    """The best searches are the ones that brought applications; the worst, the bottom of the rest.

    Never the same search on both lists, and never a 0% search under a thumbs-up.
    """
    if len(searches) < 2:
        return None
    best = [s for s in searches if s["rate"] > 0][:3]
    worst = [s for s in searches if s not in best][-3:][::-1]
    return {"best": best, "worst": worst}


def my_insights(me: dict[str, Any], market: dict[str, Any]) -> list[dict[str, Any]]:
    """What his own numbers say, most useful first."""
    insights: list[dict[str, Any]] = []
    platforms = [p for p in me["by_platform"] if p["decided"] >= MIN_FOR_SHARE and p["rate"] is not None]
    if len(platforms) >= 2:
        best = max(platforms, key=lambda p: p["rate"])
        worst = min(platforms, key=lambda p: p["rate"])
        if best["rate"] - worst["rate"] >= 0.25:
            insights.append(
                {"kind": "platform_gap", "best": best["platform"], "best_rate": best["rate"],
                 "worst": worst["platform"], "worst_rate": worst["rate"], "worst_blocked": worst["blocked"]}
            )  # fmt: skip
    tiers = me["by_tier_rate"]
    if tiers.get("top") is not None and tiers.get("review") is not None:
        insights.append({"kind": "tiers", "top": tiers["top"], "review": tiers["review"]})
    if me["mismatch_reasons"]:
        reason, count = next(iter(me["mismatch_reasons"].items()))
        total = sum(me["mismatch_reasons"].values())
        if total >= 3:
            insights.append(
                {"kind": "main_gap", "reason": reason, "share": count / total, "years": me["mismatch_years_median"]}
            )
    misses = me["filter_misses"]
    if misses and misses["mismatch"] >= 2:
        reason = max(misses["reasons"], key=misses["reasons"].get) if misses["reasons"] else None
        insights.append(
            {"kind": "filter_miss", "count": misses["mismatch"], "of": misses["promised"], "reason": reason}
        )
    hours = me["avg_hours_to_action"]
    if hours is not None and hours >= 12 and market.get("applicants"):
        insights.append({"kind": "speed", "hours": hours, "applicants": market["applicants"]["median"]})
    if me["pending"]["old"]:
        insights.append({"kind": "backlog", "old": me["pending"]["old"]})
    if me["dead_searches"]:
        insights.append({"kind": "dead_search", "labels": me["dead_searches"][:3]})
    now, before = me["decisions"]["applied"], me["prev"]["applied"]
    if before and abs(now - before) / before >= 0.3:
        insights.append({"kind": "trend", "now": now, "before": before, "market_change": _change(market)})
    return insights[:MAX_INSIGHTS]


def _change(market: dict[str, Any]) -> float | None:
    prev = market.get("in_field_prev")
    return market["in_field"] / prev - 1 if prev else None
