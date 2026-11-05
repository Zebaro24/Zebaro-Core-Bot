"""The owner's PC as the way into the Cloudflare-guarded boards.

Work.ua and Robota.ua answer the server's datacenter IP with a bot check that no browser mode
gets through, while the same pages open from a home IP; LinkedIn answers it with 429. The
owner's PC is in the VPN (10.0.0.2) and runs a small HTTP proxy bound to that address; the
server's browser opens those boards through it. Everything else goes direct.

HOME_PROXY_URL is ``http://user:password@10.0.0.2:8899``. Unset — the boards go direct as
before. Set but the PC is off or asleep — they are skipped in two seconds instead of burning
twenty on a bot check each.

The owner is not always at home, so a PC that is off is no news before noon: from ALERT_HOUR on,
the first run that finds it off says so once, and the rest of the day is quiet.
"""

import asyncio
import logging
from datetime import datetime
from urllib.parse import unquote, urlparse

from src.config import settings

logger = logging.getLogger("job_searcher.home")

_PROBE_TIMEOUT_S = 2.0
# Local hour from which a PC that is off is worth a message (05.11.2026): by noon it is on.
ALERT_HOUR = 12
ALERT_STATE_ID = "home_proxy_alert"


def home_proxy() -> dict[str, str] | None:
    """Playwright's proxy settings for the home PC, or None when it is not configured."""
    raw = settings.home_proxy_url
    if not isinstance(raw, str) or not raw:
        return None
    url = urlparse(raw)
    if not url.hostname or not url.port:
        return None
    proxy = {"server": f"{url.scheme or 'http'}://{url.hostname}:{url.port}"}
    if url.username:
        proxy["username"] = unquote(url.username)
        proxy["password"] = unquote(url.password or "")
    return proxy


async def home_proxy_up(proxy: dict[str, str]) -> bool:
    """Whether the proxy on the home PC accepts connections — the PC is on and in the VPN."""
    url = urlparse(proxy["server"])
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(url.hostname, url.port), timeout=_PROBE_TIMEOUT_S)
    except OSError:  # TimeoutError included
        logger.warning("Home PC proxy %s is not answering — its boards are skipped this run", proxy["server"])
        return False
    writer.close()
    return True


async def home_alert_due(now: datetime) -> bool:
    """Whether to tell the owner the PC is off: from ALERT_HOUR on, once a day.

    `now` is local time. Claims the day before answering yes — two runs racing send one message;
    a message lost after that is a day without one, not one per hour. A DB that cannot say → no.
    """
    if now.hour < ALERT_HOUR:
        return False
    from src.db.client import meta_collection  # the parser imports this module; tests stub the DB

    today = now.date().isoformat()
    try:
        result = await meta_collection.update_one(
            {"_id": ALERT_STATE_ID, "alerted_on": {"$ne": today}}, {"$set": {"alerted_on": today}}, upsert=True
        )
    except Exception as e:  # a duplicate key: the day is claimed already
        logger.debug("Home PC alert not claimed: %s", e)
        return False
    return bool(result.modified_count or result.upserted_id)
