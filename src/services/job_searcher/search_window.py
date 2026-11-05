"""How far back a board's "posted in the last N seconds" search looks (LinkedIn's f_TPR).

LinkedIn goes through the owner's PC, and the PC is off whenever he is away: a fixed 24 hours
lost every vacancy posted while it was off for longer (05.11.2026). The window now reaches back
to the board's last full pass — every search of it got cards — plus a margin, between a day and
a week. A window over a day pages on, up to MAX_PAGES: one page holds ten cards.

The moment of the last full pass is kept in `meta.search_window`, per board (naive UTC).
"""

import logging
from datetime import datetime

logger = logging.getLogger("job_searcher.search_window")

STATE_ID = "search_window"
DAY_S = 24 * 3600
MIN_WINDOW_S = DAY_S  # what it always was: postings show up in the search with some delay
MAX_WINDOW_S = 7 * DAY_S
MARGIN_S = 3600
# A page costs one request towards LinkedIn's 429 (a few dozen); three searches × five pages.
MAX_PAGES = 5


def window_since(last_ok: datetime | None, now: datetime) -> int:
    if last_ok is None:
        return MIN_WINDOW_S
    seconds = int((now - last_ok).total_seconds()) + MARGIN_S
    return max(MIN_WINDOW_S, min(MAX_WINDOW_S, seconds))


def pages_for(window_s: int) -> int:
    return 1 if window_s <= MIN_WINDOW_S else MAX_PAGES


async def window_seconds(platform: str, now: datetime) -> int:
    """The window for this run; the minimum when the DB cannot say."""
    from src.db.client import meta_collection  # the parser imports this module; tests stub the DB

    try:
        state = await meta_collection.find_one({"_id": STATE_ID})
    except Exception as e:
        logger.warning("Could not read the search window of %s: %s", platform, e)
        return MIN_WINDOW_S
    last_ok = (state or {}).get(platform)
    return window_since(last_ok if isinstance(last_ok, datetime) else None, now)


async def mark_full_pass(platform: str, now: datetime) -> None:
    from src.db.client import meta_collection

    try:
        await meta_collection.update_one({"_id": STATE_ID}, {"$set": {platform: now}}, upsert=True)
    except Exception as e:  # the next run looks a little further back, nothing worse
        logger.warning("Could not store the search window of %s: %s", platform, e)
