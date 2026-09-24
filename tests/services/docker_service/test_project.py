from unittest.mock import MagicMock

import pytest

from src.services.docker.project import DockerProject


def _container(name, running, memory, cpu, restarts, uptime, ports):
    container = MagicMock()
    container.get_name.return_value = name
    container.is_running.return_value = running
    container.get_memory_usage.return_value = memory
    container.get_cpu_usage.return_value = cpu
    container.get_restarts.return_value = restarts
    container.get_uptime.return_value = uptime
    container.get_open_ports.return_value = ports
    return container


@pytest.fixture
def docker_project():
    project = DockerProject("TestProject")
    c1 = _container("web", True, 512, 0.2, 1, 100, {"80", "443"})
    c2 = _container("worker", False, 256, 0.1, 2, 50, {"8080", "51820/udp"})
    project.containers = [c2, c1]
    return project, c1, c2


def test_get_status_emoji(docker_project):
    project, c1, c2 = docker_project
    assert project.get_status_emoji() == "🟡"

    c1.is_running.return_value = False
    assert project.get_status_emoji() == "🔴"

    c1.is_running.return_value = True
    c2.is_running.return_value = True
    assert project.get_status_emoji() == "🟢"


def test_running_count_and_sorting(docker_project):
    project, c1, c2 = docker_project
    assert project.running_count() == 1
    assert project.sorted_containers() == [c1, c2]  # running first


def test_totals(docker_project):
    project, _, _ = docker_project
    assert project.get_memory_usage() == 768
    assert project.get_cpu_usage() == pytest.approx(0.3)
    assert project.get_restarts() == 3
    assert project.get_uptime() == 50


def test_get_open_ports_sorts_by_number_with_the_protocol_kept(docker_project):
    project, _, _ = docker_project
    assert project.get_open_ports() == ["80", "443", "8080", "51820/udp"]
