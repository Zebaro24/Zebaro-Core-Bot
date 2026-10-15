"""Monobank's personal API: accounts, jars, statements, the webhook, the public rates.

Limits that shape this client:

* ``/personal/client-info`` and ``/personal/statement`` — one request per 60 s each;
  callers queue on a lock, so a burst becomes a slow but correct sequence;
* a statement window is at most 31 days (30 here) and at most 500 items — longer periods are
  cut into windows, a full window is split in two;
* ``/bank/currency`` is cached by Monobank for 5 minutes — so here too.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger("services.spotify.monobank")

API = "https://api.monobank.ua"
SEND_URL = "https://send.monobank.ua"
UAH = 980
USD = 840

# The limit is 31 days, but Monobank counts it its own way: a window of exactly 31 × 24 h
# was refused ("Period must be no more than 31 days") — 30 days is always accepted.
WINDOW = 30 * 86400
PAGE = 500
_INTERVAL = 61.0  # a second over the limit: Monobank counts from its own clock
_RATES_TTL = 300.0


class MonobankError(Exception):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    title: str
    currency_code: int
    balance: int
    is_jar: bool
    send_id: str = ""  # jars: "jar/XXXX", the public top-up page

    @property
    def send_url(self) -> str:
        return f"{SEND_URL}/{self.send_id}" if self.send_id else ""


class _Limiter:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.last = 0.0

    async def wait(self) -> None:
        pause = self.last + _INTERVAL - time.monotonic()
        if pause > 0:
            await asyncio.sleep(pause)
        self.last = time.monotonic()


_limiters: dict[str, _Limiter] = {}
_info_cache: tuple[float, dict] | None = None
_rates_cache: tuple[float, list[dict]] | None = None


def _limiter(name: str) -> _Limiter:
    return _limiters.setdefault(name, _Limiter())


async def _request(method: str, path: str, *, limit: str | None, **kwargs: Any) -> Any:
    headers = {"X-Token": settings.monobank_token} if path.startswith("/personal") else {}
    for attempt in range(3):
        if limit:
            limiter = _limiter(limit)
            async with limiter.lock:
                await limiter.wait()
                response = await _send(method, path, headers, **kwargs)
        else:
            response = await _send(method, path, headers, **kwargs)
        if response.status_code == 429 and limit and attempt < 2:
            logger.info("Monobank 429 on %s, waiting a minute", path)
            await asyncio.sleep(_INTERVAL)
            continue
        if response.status_code >= 400:
            raise MonobankError(f"{response.status_code} {response.text[:200]}")
        return response.json() if response.content else None
    raise MonobankError("too many requests")  # pragma: no cover


async def _send(method: str, path: str, headers: dict, **kwargs: Any) -> httpx.Response:
    try:
        async with httpx.AsyncClient(base_url=API, timeout=30) as client:
            return await client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError as e:
        raise MonobankError(f"{type(e).__name__}: {e}") from e


def configured() -> bool:
    return bool(settings.monobank_token)


async def client_info(fresh: bool = False) -> dict:
    """Accounts, jars and the webhook URL; reused for a minute (the endpoint's own limit)."""
    global _info_cache
    if not fresh and _info_cache and time.monotonic() - _info_cache[0] < _INTERVAL:
        return _info_cache[1]
    data = await _request("GET", "/personal/client-info", limit="client-info")
    _info_cache = (time.monotonic(), data)
    return dict(data)


def parse_accounts(info: dict) -> list[Account]:
    cards = [
        Account(
            id=a["id"],
            title=f"{a.get('type', 'card')} {_currency_name(a['currencyCode'])}",
            currency_code=a["currencyCode"],
            balance=a["balance"],
            is_jar=False,
        )
        for a in info.get("accounts", [])
    ]
    jars = [
        Account(
            id=j["id"],
            title=j.get("title", "jar"),
            currency_code=j["currencyCode"],
            balance=j["balance"],
            is_jar=True,
            send_id=j.get("sendId", ""),
        )
        for j in info.get("jars", [])
    ]
    return cards + jars


def _currency_name(code: int) -> str:
    return {UAH: "UAH", USD: "USD", 978: "EUR"}.get(code, str(code))


async def statement(account: str, start: int, end: int) -> list[dict]:
    """Every statement item of the account in [start, end], oldest first, deduplicated."""
    items: dict[str, dict] = {}
    window_start = start
    while window_start < end:
        window_end = min(window_start + WINDOW, end)
        try:
            window = await _window(account, window_start, window_end)
        except MonobankError as e:
            # Before the account existed (a jar opened later than the plan): "'to' out of bounds".
            if "out of bounds" not in str(e):
                raise
            logger.info("Statement of %s: no account yet before %s", account, window_end)
            window = []
        for item in window:
            items[item["id"]] = item
        window_start = window_end
    return sorted(items.values(), key=lambda i: i["time"])


async def _window(account: str, start: int, end: int) -> list[dict]:
    items: list[dict] = await _request("GET", f"/personal/statement/{account}/{start}/{end}", limit="statement")
    if len(items) >= PAGE and end - start > 60:
        middle = (start + end) // 2
        return await _window(account, start, middle) + await _window(account, middle, end)
    return items


async def set_webhook(url: str) -> None:
    """Monobank checks the URL with a GET right away: the web server must already answer."""
    await _request("POST", "/personal/webhook", limit=None, json={"webHookUrl": url})


async def rate(code: int = USD) -> float:
    """UAH for one unit at Monobank's selling rate — what a card payment abroad costs."""
    global _rates_cache
    if not _rates_cache or time.monotonic() - _rates_cache[0] > _RATES_TTL:
        try:
            _rates_cache = (time.monotonic(), await _request("GET", "/bank/currency", limit=None))
        except MonobankError:
            # Keep the last good rates (or nothing) for another TTL instead of asking again
            # on every screen while Monobank throttles.
            _rates_cache = (time.monotonic(), _rates_cache[1] if _rates_cache else [])
            if not _rates_cache[1]:
                raise
    for row in _rates_cache[1]:
        if row.get("currencyCodeA") == code and row.get("currencyCodeB") == UAH:
            return float(row.get("rateSell") or row.get("rateCross") or 0)
    raise MonobankError(f"no rate for currency {code}")
