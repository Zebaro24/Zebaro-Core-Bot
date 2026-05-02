"""HTML formatters for Docker-related Telegram messages.

Presentation logic lives here — services stay free of Telegram/HTML concerns.
"""

from src.services.docker.manager import DockerManager


def format_manager_info(manager: DockerManager) -> str:
    """Full projects overview: all projects + total memory + open ports."""
    text = "<b>🐳 Docker проекты:</b>\n\n"
    for project in manager.project_dict.values():
        text += f"{project.get_short_info()}\n\n"
    text += manager.get_memory_used_text()
    if ports := manager.get_open_ports():
        text += f"🌐 Open ports: {', '.join(ports)}\n"
    return text
