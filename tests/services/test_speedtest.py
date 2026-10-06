import httpx
import pytest

from src.interfaces.tg.formatters.speedtest import format_speedtest_results
from src.services.speedtest import manager as speed
from src.services.speedtest.manager import SpeedTestManager


def _transport(fail_on: str | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail_on and request.url.path == fail_on:
            return httpx.Response(503)
        if request.url.path == "/cdn-cgi/trace":
            return httpx.Response(200, text="ip=1.2.3.4\ncolo=FRA\nloc=DE\n")
        if request.url.path == "/__down":
            return httpx.Response(200, content=b"0" * int(request.url.params["bytes"]))
        return httpx.Response(200)

    return httpx.MockTransport(handler)


@pytest.fixture
def fast(mocker):
    mocker.patch.object(speed, "PHASE_SECONDS", 0.05)
    mocker.patch.object(speed, "DOWNLOAD_CHUNK", 10_000)
    mocker.patch.object(speed, "UPLOAD_CHUNK", 10_000)


def _manager(transport: httpx.MockTransport, mocker) -> SpeedTestManager:
    client = httpx.AsyncClient(base_url=speed.BASE_URL, transport=transport)
    mocker.patch.object(speed.httpx, "AsyncClient", return_value=client)
    return SpeedTestManager()


@pytest.mark.asyncio
async def test_a_full_run_fills_every_result(fast, mocker):
    manager = _manager(_transport(), mocker)

    assert await manager.initialize()
    await manager.prepare()
    await manager.test_download()
    await manager.test_upload()

    assert manager.is_complete() and manager.error is None
    assert manager.results["server"]["name"] == "Франкфурт"
    text = format_speedtest_results(manager)
    assert "Готово" in text and "Mbps" in text and "Пинг" in text


@pytest.mark.asyncio
async def test_a_failed_step_shows_the_error_instead_of_freezing(fast, mocker):
    manager = _manager(_transport(fail_on="/__up"), mocker)

    await manager.initialize()
    await manager.prepare()
    await manager.test_download()
    assert await manager.test_upload() is None

    assert manager.error and manager.error.startswith("отдача")
    assert "Не получилось" in format_speedtest_results(manager)


def test_progress_is_drawn_while_a_step_runs():
    manager = SpeedTestManager()
    manager.results["server"] = {"sponsor": "Cloudflare", "name": "Вена", "country": "AT", "latency": 12.0}
    manager.progress = {"phase": "download", "done": 50, "total": 100}

    text = format_speedtest_results(manager, frame=1)

    assert "▰▰▰▰▰▰▱▱▱▱▱▱" in text and "50%" in text
