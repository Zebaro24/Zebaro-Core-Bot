"""The search runs of a day, counted per board (26.11.2026).

A vacancy row says what was found and kept; it cannot say a board was opened and showed nothing,
or was not opened at all because the home PC was off. The owner could not tell a quiet market from
a broken parser ("no vacancies all day — is something broken?"), and the weekly review called
boards silent that were only skipped. So every run adds its figures to the day's kv row
`job_day:<YYYY-MM-DD>` (the owner's clock):

* `runs`, `browser_down` (Playwright was not there), `home_down` (the PC did not answer),
  `crashed` (the run stopped on an error);
* per board: `searches` opened, `cards` on their list pages (known ones included), `failed`
  pages, `skipped` searches (the home PC was off).

`day_stats` puts that next to the day's stored vacancies (new, filtered out and why, surfaced) for
the day's Telegram message; `period_sources` sums it for the digest. Both are None when nothing was
recorded — before this release, or with the DB down — so a missing count is never read as zero.
"""

import logging
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_

from src.db import sql
from src.services.job_searcher import store

logger = logging.getLogger("job_searcher.runs")

KEY = "job_day:{}"
COUNTS = ("searches", "cards", "failed", "skipped")
SURFACED = ("top", "sent", "review")
REJECTED = "rejected_by_filter"
DUPLICATE = "duplicate"


def new_counts() -> dict[str, int]:
    return dict.fromkeys(COUNTS, 0)


def local_day(now: datetime | None = None) -> str:
    return (now or datetime.now()).date().isoformat()  # the process's clock is the owner's (TZ)


def utc_bounds(day: str) -> tuple[datetime, datetime]:
    """The owner's day as naive UTC, the way `found_at` is stored."""
    start = datetime.combine(date.fromisoformat(day), time()).astimezone()  # local midnight
    end = start + timedelta(days=1)
    return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


async def record_run(
    counts: dict[str, dict[str, int]],
    *,
    browser_down: bool,
    home_down: bool,
    crashed: bool = False,
    now: datetime | None = None,
) -> None:
    """Add one run to its day. Runs never overlap (job_notification's lock), so read-then-write is safe."""
    now = now or datetime.now()
    key = KEY.format(local_day(now))
    try:
        day = await sql.kv_get(key) or {}
        platforms: dict[str, dict[str, int]] = {name: dict(c) for name, c in (day.get("platforms") or {}).items()}
        for name, run in counts.items():
            total = platforms.setdefault(name, new_counts())
            for field in COUNTS:
                total[field] = total.get(field, 0) + run.get(field, 0)
        await sql.kv_merge(
            key,
            {
                "runs": int(day.get("runs") or 0) + 1,
                "browser_down": int(day.get("browser_down") or 0) + browser_down,
                "home_down": int(day.get("home_down") or 0) + home_down,
                "crashed": int(day.get("crashed") or 0) + crashed,
                "last_run": now.strftime("%H:%M"),
                "platforms": platforms,
            },
        )
    except Exception as e:  # a lost count is a gap in the day's figures, never a failed run
        logger.warning("Run figures not recorded: %s", e)


def _board(name: str, run: dict[str, int], docs: list[dict[str, Any]]) -> dict[str, Any]:
    kept = [doc for doc in docs if doc.get("user_status") != DUPLICATE]
    return {
        "platform": name,
        **{field: int(run.get(field, 0)) for field in COUNTS},
        "new": len(kept),
        "repeats": len(docs) - len(kept),
        "filtered_out": sum(doc.get("moderation") == REJECTED for doc in kept),
        "surfaced": sum(doc.get("moderation") in SURFACED for doc in kept),
    }


def _summarise(platforms: dict[str, dict[str, int]], docs: list[dict[str, Any]]) -> dict[str, Any]:
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        by_platform.setdefault(doc.get("platform_name") or "?", []).append(doc)
    names = sorted(set(platforms) | set(by_platform), key=lambda n: -int((platforms.get(n) or {}).get("cards", 0)))
    boards = [_board(name, platforms.get(name) or {}, by_platform.get(name, [])) for name in names]
    kept = [doc for doc in docs if doc.get("user_status") != DUPLICATE]
    tiers = Counter(doc.get("moderation") for doc in kept)
    reasons = Counter(doc.get("filter_reason") or "?" for doc in kept if doc.get("moderation") == REJECTED)
    return {
        "platforms": boards,
        "cards": sum(board["cards"] for board in boards),
        "new": len(kept),
        "repeats": len(docs) - len(kept),
        "filtered_out": tiers.get(REJECTED, 0),
        "reasons": dict(reasons.most_common()),
        "by_tier": {tier: tiers.get(tier, 0) for tier in SURFACED},
        # Pages loaded, and not one card on any: a broken selector or a block. A board whose every
        # page failed to load is not this — it shows as `failed`.
        "broken": [b["platform"] for b in boards if b["searches"] > b["failed"] and not b["cards"]],
        # Not opened at all this period: every search of it waited for the home PC.
        "not_searched": [b["platform"] for b in boards if b["skipped"] and not b["searches"]],
        "skipped": [b["platform"] for b in boards if b["skipped"]],
    }


async def day_stats(day: str) -> dict[str, Any] | None:
    """The day's runs and vacancies; None before the day's first recorded run or with the DB down."""
    try:
        recorded = await sql.kv_get(KEY.format(day))
        if not recorded:
            return None
        start, end = utc_bounds(day)
        docs = await store.find(and_(store.J.found_at >= start, store.J.found_at < end), description=False)
    except Exception as e:
        logger.warning("Day figures unavailable: %s", e)
        return None
    return {
        "day": day,
        "runs": int(recorded.get("runs") or 0),
        "last_run": recorded.get("last_run"),
        "browser_down": int(recorded.get("browser_down") or 0),
        "home_down": int(recorded.get("home_down") or 0),
        "crashed": int(recorded.get("crashed") or 0),
        **_summarise(recorded.get("platforms") or {}, docs),
    }


async def period_sources(since: datetime, until: datetime, found: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Per board over [since, until] (naive UTC): the recorded runs next to the vacancies `found` in it.
    None when no day of the period has a record."""
    platforms: dict[str, dict[str, int]] = {}
    recorded = 0
    first = since.replace(tzinfo=UTC).astimezone().date()
    last = until.replace(tzinfo=UTC).astimezone().date()
    try:
        for offset in range((last - first).days + 1):
            day = await sql.kv_get(KEY.format((first + timedelta(days=offset)).isoformat()))
            if not day:
                continue
            recorded += 1
            for name, run in (day.get("platforms") or {}).items():
                total = platforms.setdefault(name, new_counts())
                for field in COUNTS:
                    total[field] += int(run.get(field, 0))
    except Exception as e:
        logger.warning("Run figures unavailable for the digest: %s", e)
        return None
    if not recorded:
        return None
    return {"days_recorded": recorded, **_summarise(platforms, found)}
