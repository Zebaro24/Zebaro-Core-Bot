"""HTML formatter for SpeedTest Telegram messages.

Presentation logic lives here — SpeedTestManager stays free of HTML concerns. The message is
redrawn every second or so while a step runs (handlers/admin/server_speed.py), so a frame
counter turns the spinner and the progress bar fills with the time and bytes of the step.
"""

import html

from src.services.speedtest.manager import SpeedTestManager

_SPINNER = "◐◓◑◒"
_BAR_CELLS = 12
# The scale of the speed bars: a gigabit line fills them.
_FULL_SCALE_MBPS = 1000
_LINE = "━━━━━━━━━━━━━━━━━━━━━━━"


def _bar(share: float) -> str:
    filled = max(0, min(_BAR_CELLS, round(share * _BAR_CELLS)))
    return "▰" * filled + "▱" * (_BAR_CELLS - filled)


def _rating(mbps: float) -> str:
    if mbps >= 500:
        return "🚀"
    if mbps >= 100:
        return "⚡"
    if mbps >= 20:
        return "🙂"
    return "🐢"


def _speed(label: str, mbps: float) -> str:
    return (
        f"{label} <b>{mbps:.1f} Mbps</b> {_rating(mbps)}\n"
        f"<code>{_bar(mbps / _FULL_SCALE_MBPS)}</code> {mbps / 8:.1f} MB/s\n"
    )


def _running(manager: SpeedTestManager, phase: str, label: str, frame: int) -> str:
    spinner = _SPINNER[frame % len(_SPINNER)]
    progress = manager.progress if manager.progress.get("phase") == phase else {}
    total = progress.get("total") or 0
    if not total:
        return f"{label} {spinner} <i>разгоняемся…</i>\n"
    share = progress["done"] / total
    return f"{label} {spinner} <code>{_bar(share)}</code> {share:.0%}\n"


def format_speedtest_results(manager: SpeedTestManager, frame: int = 0) -> str:
    text = f"<b>📡 Скорость интернета на сервере</b>\n{_LINE}\n"
    results = manager.results

    if "server" in results:
        server = results["server"]
        place = ", ".join(str(item) for item in (server.get("name"), server.get("country")) if item)
        text += f"🌍 {html.escape(str(server.get('sponsor', '?')))} — {html.escape(place)}\n"
        if "latency" in server:
            jitter = f" · джиттер {results['jitter']:.1f} ms" if "jitter" in results else ""
            text += f"🏓 Пинг: <b>{float(server['latency']):.1f} ms</b>{jitter}\n\n"
        elif not manager.error:
            text += f"🏓 {_SPINNER[frame % len(_SPINNER)]} <i>меряю пинг…</i>\n\n"
    elif not manager.error:
        text += f"{_SPINNER[frame % len(_SPINNER)]} <i>Ищу ближайший сервер…</i>\n\n"

    if "download" in results:
        text += _speed("⬇️ Загрузка", results["download"])
    elif "latency" in results.get("server", {}) and not manager.error:
        text += _running(manager, "download", "⬇️ Загрузка", frame)

    if "upload" in results:
        text += _speed("⬆️ Отдача", results["upload"])
    elif "download" in results and not manager.error:
        text += _running(manager, "upload", "⬆️ Отдача", frame)

    text += f"{_LINE}\n"
    if manager.error:
        text += f"❌ <b>Не получилось</b> — {html.escape(manager.error)}"
    elif manager.is_complete():
        text += "🎉 <b>Готово!</b> Хомячок 🐹 добежал и отдыхает."
    else:
        text += "⏳ <i>Хомячок 🐹💨 бежит…</i>"
    return text
