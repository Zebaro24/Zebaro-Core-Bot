import asyncio
from concurrent.futures import ThreadPoolExecutor

import speedtest


class SpeedTestManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._st = speedtest.Speedtest()
        self.results = {}

    async def _run_in_thread(self, func, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    async def prepare(self):
        await self._run_in_thread(self._st.get_servers)
        best = await self._run_in_thread(self._st.get_best_server)
        self.results["server"] = best
        return best

    async def test_download(self):
        download_speed = await self._run_in_thread(self._st.download)
        self.results["download"] = download_speed / 1_000_000  # в Мбит/с
        return self.results["download"]

    async def test_upload(self):
        upload_speed = await self._run_in_thread(self._st.upload)
        self.results["upload"] = upload_speed / 1_000_000  # в Мбит/с
        return self.results["upload"]

    def get_text(self):
        text = "<b>📡 SpeedTest Report</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━\n"

        if "server" in self.results:
            server = self.results["server"]
            text += f"🌍 <b>Server:</b> {server.get('sponsor', 'Unknown')}\n"
            location = f"{server.get('name', 'Unknown')} ({server.get('country', 'N/A')})"
            text += f"🏙 <b>Location:</b> {location}\n"
            text += f"🏓 <b>Ping:</b> {server['latency']:.2f} ms\n\n"
        else:
            text += "🌀 <i>Прогрев спутников...</i>\n"
            text += "🌍 <i>В поисках самого быстрого места на Земле...</i>\n"
            text += "🐢 <i>Измерение пинга...</i>\n\n"

        if "download" in self.results:
            text += f"⬇️ <b>Download:</b> {self.results['download']:.2f} Mbps\n"
        else:
            text += "🚀 <i>Загрузка битов и байтов...</i>\n"

        if "upload" in self.results:
            text += f"⬆️ <b>Upload:</b> {self.results['upload']:.2f} Mbps\n"
        else:
            text += "☁️ <i>Загрузка ваших нулей и единиц...</i>\n"

        text += "━━━━━━━━━━━━━━━━━━━━━━━\n"

        required_keys = ["server", "download", "upload"]
        if all(key in self.results for key in required_keys):
            text += "🎉 <b>Все готово! Ваш интернет-хомячок 🐹💨 завершил свой спринт и теперь заслуженно отдыхает.</b>"
        else:
            text += "⏳ <b>Держитесь крепче — ваш интернет-хомячок мчится на полной скорости!</b> 🐹💨"

        return text

    def __str__(self):
        return f"<SpeedTestManager {self.results}>"
