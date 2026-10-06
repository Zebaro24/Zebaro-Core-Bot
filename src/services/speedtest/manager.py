"""The server's line speed, measured against Cloudflare's speed test endpoints.

speedtest-cli (speedtest.net) stopped working: every server timed out, the ping came back as
1 800 000 ms and both speeds as 0 Mbps (checked 06.10.2026), and the library is no longer
maintained. speed.cloudflare.com serves plain HTTP — `__down?bytes=N` sends N bytes,
`__up` takes a POST — so the test is a few async requests, timed: no threads, no extra
dependency, and the progress is real bytes.
"""

import logging
import time
from itertools import pairwise
from statistics import median
from typing import Any

import httpx

logger = logging.getLogger("speedtest.manager")

BASE_URL = "https://speed.cloudflare.com"
# Each direction runs for about this long, or until the byte cap: long enough for the speed to
# settle, short enough for a chat message.
PHASE_SECONDS = 8.0
DOWNLOAD_CHUNK = 25_000_000
UPLOAD_CHUNK = 5_000_000
MAX_BYTES = 400_000_000
PING_COUNT = 8
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Cloudflare's data centres the server is likely to hit, for a readable name.
_COLOS = {"FRA": "Франкфурт", "AMS": "Амстердам", "DUS": "Дюссельдорф", "VIE": "Вена", "WAW": "Варшава",
          "HEL": "Хельсинки", "ARN": "Стокгольм", "CDG": "Париж", "LHR": "Лондон", "MUC": "Мюнхен"}  # fmt: skip


class SpeedTestManager:
    """One speed test, step by step, so the Telegram message can follow it.

    Any step that fails leaves `error` set instead of raising: a crash used to leave the
    message frozen on "the hamster is running" forever.
    """

    def __init__(self) -> None:
        self.results: dict[str, Any] = {}
        self.error: str | None = None
        # The step running now and how far it got, in percent: {"phase": "download", "done": 40, "total": 100}.
        self.progress: dict[str, Any] = {}
        self._client: httpx.AsyncClient | None = None

    async def _fail(self, step: str, e: Exception) -> None:
        logger.warning("Speed test failed at %s: %s", step, e)
        self.error = f"{step}: {e}"[:200]
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def initialize(self) -> bool:
        """Which Cloudflare data centre answers and the server's address as it sees it."""
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=_TIMEOUT)
        try:
            response = await self._client.get("/cdn-cgi/trace")
            response.raise_for_status()
        except Exception as e:
            await self._fail("Cloudflare не ответил", e)
            return False
        trace = dict(line.split("=", 1) for line in response.text.splitlines() if "=" in line)
        colo = trace.get("colo", "?")
        self.results["server"] = {"sponsor": "Cloudflare", "name": _COLOS.get(colo, colo), "country": trace.get("loc")}
        return True

    async def prepare(self) -> dict[str, object] | None:
        """Ping: the time of an empty request, several times — the median, and how much it jitters."""
        if self._client is None or self.error:
            return None
        times: list[float] = []
        try:
            for _ in range(PING_COUNT):
                start = time.perf_counter()
                await self._client.get("/__down", params={"bytes": 0})
                times.append((time.perf_counter() - start) * 1000)
        except Exception as e:
            await self._fail("пинг", e)
            return None
        # The first request pays for the TLS handshake.
        times = times[1:] or times
        server: dict[str, object] = self.results["server"]
        server["latency"] = median(times)
        self.results["jitter"] = median(abs(a - b) for a, b in pairwise(times)) if len(times) > 1 else 0.0
        return server

    def _tick(self, phase: str, started: float, sent: int) -> None:
        share = max((time.perf_counter() - started) / PHASE_SECONDS, sent / MAX_BYTES)
        self.progress = {"phase": phase, "done": min(99, round(share * 100)), "total": 100}

    def _done(self, phase: str, sent: int, started: float) -> float:
        mbps = sent * 8 / (time.perf_counter() - started) / 1_000_000
        self.results[phase] = mbps
        self.progress = {}
        logger.info("%s: %.1f Mbps", phase.capitalize(), mbps)
        return mbps

    async def test_download(self) -> float | None:
        if self._client is None or self.error:
            return None
        started, received = time.perf_counter(), 0
        self._tick("download", started, 0)
        try:
            while time.perf_counter() - started < PHASE_SECONDS and received < MAX_BYTES:
                params = {"bytes": DOWNLOAD_CHUNK}
                async with self._client.stream("GET", "/__down", params=params) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        self._tick("download", started, received)
        except Exception as e:
            await self._fail("загрузка", e)
            return None
        return self._done("download", received, started)

    async def test_upload(self) -> float | None:
        if self._client is None or self.error:
            return None
        payload = b"0" * UPLOAD_CHUNK
        started, sent = time.perf_counter(), 0
        self._tick("upload", started, 0)
        try:
            while time.perf_counter() - started < PHASE_SECONDS and sent < MAX_BYTES:
                response = await self._client.post("/__up", content=payload)
                response.raise_for_status()
                sent += len(payload)
                self._tick("upload", started, sent)
        except Exception as e:
            await self._fail("отдача", e)
            return None
        mbps = self._done("upload", sent, started)
        await self.close()
        return mbps

    def is_complete(self) -> bool:
        return all(k in self.results for k in ("server", "download", "upload"))

    def __str__(self) -> str:
        return f"<SpeedTestManager {self.results}>"
