"""Docker screens of /server_status as Telegram rich messages.

Presentation lives here — services stay free of Telegram/HTML concerns. Tables, not blocks
of "label: value" lines: with a dozen projects the old text took several screens.
Rows follow the same order as the buttons under the message (keyboards/docker.py).
"""

from html import escape

from src.services.docker.container import DockerContainer
from src.services.docker.manager import DockerManager
from src.services.docker.project import DockerProject
from src.utils.format_memory import format_memory
from src.utils.format_time import format_duration

LOG_TAIL = 20

_TABLE = "<table bordered striped compact>"


def _cpu(percent: float) -> str:
    # get_cpu_usage() is already a percent of one core; it used to be multiplied by 100 again.
    return f"{percent:.1f}%" if percent < 10 else f"{percent:.0f}%"


def _uptime(seconds: int) -> str:
    return format_duration(seconds) or "—"


def _ports(ports: list[str] | set[str]) -> str:
    return ", ".join(escape(p) for p in ports) if ports else "—"


def format_manager_rich(manager: DockerManager) -> str:
    projects = manager.sorted_projects()
    running = sum(1 for _, p in projects if p.running_count())
    parts = [
        f"<h3>🐳 Docker · {len(projects)} проектов, работают {running}</h3>",
        f"<p>💾 RAM <b>{format_memory(manager.get_memory_used())}</b> из {format_memory(manager.get_memory_total())}"
        f" · 🖥️ CPU <b>{_cpu(manager.get_cpu_used())}</b></p>",
    ]
    rows = "".join(
        f"<tr><td>{project.get_status_emoji()} {escape(project.name)}</td>"
        f'<td align="center">{project.running_count()}/{len(project.containers)}</td>'
        f'<td align="right">{format_memory(project.get_memory_usage())}</td>'
        f'<td align="right">{_cpu(project.get_cpu_usage())}</td>'
        f"<td>{_uptime(project.get_uptime())}</td></tr>"
        for _, project in projects
    )
    parts.append(f"{_TABLE}<tr><th>Проект</th><th>Конт.</th><th>RAM</th><th>CPU</th><th>Аптайм</th></tr>{rows}</table>")
    parts.append(f"<p>🌐 Открытые порты: <b>{_ports(manager.get_open_ports())}</b></p>")
    return "".join(parts)


def format_project_rich(project: DockerProject) -> str:
    parts = [
        f"<h3>🚀 {escape(project.name)} {project.get_status_emoji()}</h3>",
        f"<p>Работают <b>{project.running_count()}</b> из {len(project.containers)}"
        f" · 💾 {format_memory(project.get_memory_usage())} · 🖥️ {_cpu(project.get_cpu_usage())}"
        f" · 🔁 рестартов {project.get_restarts()}</p>",
    ]
    rows = "".join(
        f"<tr><td>{c.get_status_emoji()} {escape(c.get_name())}</td>"
        f'<td align="right">{format_memory(c.get_memory_usage())}</td>'
        f'<td align="right">{_cpu(c.get_cpu_usage())}</td>'
        f"<td>{_uptime(c.get_uptime())}</td>"
        f"<td>{_ports(sorted(c.get_open_ports()))}</td></tr>"
        for c in project.sorted_containers()
    )
    parts.append(
        f"{_TABLE}<tr><th>Контейнер</th><th>RAM</th><th>CPU</th><th>Аптайм</th><th>Порты</th></tr>{rows}</table>"
    )
    return "".join(parts)


def format_container_rich(container: DockerContainer, logs: str | None = None) -> str:
    rows = [
        ("Статус", f"{container.get_status_emoji()} {escape(container.get_status())}"),
        ("Проект", escape(container.get_project_name())),
        ("Образ", escape(container.get_image()) or "—"),
        ("RAM", format_memory(container.get_memory_usage())),
        ("CPU", _cpu(container.get_cpu_usage())),
        ("Аптайм", _uptime(container.get_uptime())),
        ("Рестарты", str(container.get_restarts())),
        ("Порты", _ports(sorted(container.get_open_ports()))),
    ]
    parts = [
        f"<h3>📦 {escape(container.get_name())}</h3>",
        _TABLE + "".join(f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows) + "</table>",
    ]
    if logs:
        parts.append(
            f"<details><summary>📜 Последние {LOG_TAIL} строк лога</summary><pre>{escape(logs)}</pre></details>"
        )
    return "".join(parts)
