"""HTML formatter for SpeedTest Telegram messages.

Presentation logic lives here — SpeedTestManager stays free of HTML concerns.
"""

from src.services.speedtest.manager import SpeedTestManager


def format_speedtest_results(manager: SpeedTestManager) -> str:
    text = "<b>📡 SpeedTest Report</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n"

    if "server" in manager.results:
        server = manager.results["server"]
        text += f"🌍 <b>Server:</b> {server.get('sponsor', 'Unknown')}\n"
        location = f"{server.get('name', 'Unknown')} ({server.get('country', 'N/A')})"
        text += f"🏙 <b>Location:</b> {location}\n"
        text += f"🏓 <b>Ping:</b> {server['latency']:.2f} ms\n\n"
    else:
        text += "🌀 <i>Прогрев спутников...</i>\n"
        text += "🌍 <i>В поисках самого быстрого места на Земле...</i>\n"
        text += "🐢 <i>Измерение пинга...</i>\n\n"

    if "download" in manager.results:
        text += f"⬇️ <b>Download:</b> {manager.results['download']:.2f} Mbps\n"
    else:
        text += "🚀 <i>Загрузка битов и байтов...</i>\n"

    if "upload" in manager.results:
        text += f"⬆️ <b>Upload:</b> {manager.results['upload']:.2f} Mbps\n"
    else:
        text += "☁️ <i>Загрузка ваших нулей и единиц...</i>\n"

    text += "━━━━━━━━━━━━━━━━━━━━━━━\n"

    if manager.is_complete():
        text += "🎉 <b>Все готово! Ваш интернет-хомячок 🐹💨 завершил свой спринт и теперь заслуженно отдыхает.</b>"
    else:
        text += "⏳ <b>Держитесь крепче — ваш интернет-хомячок мчится на полной скорости!</b> 🐹💨"

    return text
