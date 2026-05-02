import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import speedtest

logger = logging.getLogger("speedtest.manager")


class SpeedTestManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._st: speedtest.Speedtest | None = None
        self.results: dict = {}
        self.error: str | None = None

    async def _run_in_thread(self, func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    async def initialize(self) -> bool:
        try:
            self._st = await self._run_in_thread(lambda: speedtest.Speedtest(secure=True))
            return True
        except speedtest.ConfigRetrievalError as e:
            logger.error("Failed to initialize speedtest: %s", e)
            self.error = f"Сервис недоступен (HTTP {e})"
            return False

    async def prepare(self) -> dict[str, object] | None:
        if self._st is None:
            return None
        logger.info("Fetching speedtest servers...")
        await self._run_in_thread(self._st.get_servers)
        best: dict[str, object] = dict(await self._run_in_thread(self._st.get_best_server))
        self.results["server"] = best
        logger.info("Best server: %s (%s)", best.get("sponsor"), best.get("name"))
        return best

    async def test_download(self) -> float | None:
        if self._st is None:
            return None
        logger.info("Testing download speed...")
        download_speed = await self._run_in_thread(self._st.download)
        self.results["download"] = float(download_speed) / 1_000_000
        logger.info("Download: %.2f Mbps", self.results["download"])
        return float(self.results["download"])

    async def test_upload(self) -> float | None:
        if self._st is None:
            return None
        logger.info("Testing upload speed...")
        upload_speed = await self._run_in_thread(self._st.upload)
        self.results["upload"] = float(upload_speed) / 1_000_000
        logger.info("Upload: %.2f Mbps", self.results["upload"])
        return float(self.results["upload"])

    def is_complete(self) -> bool:
        return all(k in self.results for k in ("server", "download", "upload"))

    def __str__(self) -> str:
        return f"<SpeedTestManager {self.results}>"
