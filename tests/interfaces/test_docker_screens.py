from unittest.mock import MagicMock

from aiogram.types import InlineKeyboardButton

from src.interfaces.tg.formatters.docker import format_container_rich, format_manager_rich, format_project_rich
from src.interfaces.tg.keyboards.docker import get_docker_container_kb, get_docker_manager_kb, get_docker_project_kb
from src.interfaces.tg.keyboards.grid import button_grid


def _buttons(n):
    return [InlineKeyboardButton(text=str(i), callback_data=f"item:{i}") for i in range(n)]


def test_grid_two_columns_on_one_page():
    rows = button_grid(_buttons(5), page_callback=lambda p: f"page:{p}")
    assert [[b.text for b in row] for row in rows] == [["0", "1"], ["2", "3"], ["4"]]


def test_grid_pages_past_ten_items_and_wraps_around():
    rows = button_grid(_buttons(23), page=2, page_callback=lambda p: f"page:{p}")
    assert [b.text for b in rows[0]] == ["20", "21"]
    nav = rows[-1]
    assert [b.text for b in nav] == ["◀️", "3 / 3", "▶️"]
    assert [b.callback_data for b in nav] == ["page:1", "page:2", "page:0"]


def test_grid_snaps_a_page_that_no_longer_exists():
    rows = button_grid(_buttons(12), page=7, page_callback=lambda p: f"page:{p}")
    assert rows[-1][1].text == "2 / 2"


def _container(name, running=True, ports=("8000",)):
    c = MagicMock()
    c.get_name.return_value = name
    c.is_running.return_value = running
    c.get_status_emoji.return_value = "🟢" if running else "🔴"
    c.get_status.return_value = "Running" if running else "Exited"
    c.get_memory_usage.return_value = 100 * 1024**2
    c.get_cpu_usage.return_value = 4.2  # already a percent
    c.get_uptime.return_value = 3600
    c.get_restarts.return_value = 0
    c.get_open_ports.return_value = set(ports)
    c.get_project_name.return_value = "Zebaro-Core"
    c.get_image.return_value = "ghcr.io/zebaro24/zebaro-core-bot:latest"
    return c


def _project(name, containers):
    p = MagicMock()
    p.name = name
    p.containers = containers
    p.sorted_containers.return_value = sorted(containers, key=lambda c: not c.is_running())
    p.running_count.return_value = sum(c.is_running() for c in containers)
    p.get_status_emoji.return_value = "🟢" if p.running_count.return_value else "🔴"
    p.get_memory_usage.return_value = 300 * 1024**2
    p.get_cpu_usage.return_value = 4.2
    p.get_uptime.return_value = 3600
    p.get_restarts.return_value = 1
    return p


def _manager(projects):
    m = MagicMock()
    m.sorted_projects.return_value = [(p.name, p) for p in projects]
    m.get_memory_used.return_value = 2 * 1024**3
    m.get_memory_total.return_value = 8 * 1024**3
    m.get_cpu_used.return_value = 12.5
    m.get_open_ports.return_value = ["80", "8000", "51820/udp"]
    return m


def test_manager_screen_is_one_table_with_ports():
    core = _project("Zebaro-Core", [_container("bot"), _container("db")])
    old = _project("Old<Proj>", [_container("x", running=False)])
    html = format_manager_rich(_manager([core, old]))

    assert "2 проектов, работают 1" in html
    assert "<table bordered striped compact>" in html
    assert "<td>🟢 Zebaro-Core</td>" in html
    assert "Old&lt;Proj&gt;" in html
    assert "4.2%" in html and "420" not in html  # no second ×100
    assert "80, 8000, 51820/udp" in html


def test_manager_buttons_are_two_per_row_with_status():
    projects = [_project(f"P{i}", [_container("c")]) for i in range(3)]
    kb = get_docker_manager_kb(_manager(projects))
    texts = [[b.text for b in row] for row in kb.inline_keyboard]
    assert texts == [["🟢 P0", "🟢 P1"], ["🟢 P2"], ["Обновить 🔄"]]


def test_project_screen_lists_containers_with_ports():
    project = _project("Zebaro-Core", [_container("bot", ports=("8000",)), _container("vpn", ports=("51820/udp",))])
    html = format_project_rich(project)
    assert "<th>Порты</th>" in html
    assert "51820/udp" in html
    kb = get_docker_project_kb(project)
    assert kb.inline_keyboard[0][0].text == "🟢 bot"


def test_container_screen_folds_escaped_logs_and_goes_back_to_its_project():
    container = _container("bot")
    html = format_container_rich(container, "line <1>\nline 2")

    assert "<th>Образ</th><td>ghcr.io/zebaro24/zebaro-core-bot:latest</td>" in html
    assert "<details><summary>📜 Последние 20 строк лога</summary><pre>line &lt;1&gt;" in html

    kb = get_docker_container_kb(container)
    assert kb.inline_keyboard[0][0].text == "Стоп ⏹️"
    assert "docker_project:get:Zebaro-Core" in (kb.inline_keyboard[-1][1].callback_data or "")
