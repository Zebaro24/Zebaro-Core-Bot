"""The owner's PC as the way into the Cloudflare-guarded boards.

Work.ua, Robota.ua and HappyMonday answer the server's datacenter IP with a bot check that no
browser mode gets through, while the same pages open from a home IP. The owner's PC is in the
VPN (10.0.0.2) and runs a small HTTP proxy bound to that address; the server's browser opens
those three boards through it. Everything else goes direct.

HOME_PROXY_URL is ``http://user:password@10.0.0.2:8899``. Unset — the boards go direct as
before. Set but the PC is off or asleep — they are skipped in two seconds instead of burning
twenty on a bot check each.
"""

import asyncio
import logging
from urllib.parse import unquote, urlparse

from src.config import settings

logger = logging.getLogger("job_searcher.home")

_PROBE_TIMEOUT_S = 2.0


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
