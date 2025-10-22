from unittest.mock import MagicMock

import pytest

from app.services.docker_service.project import DockerProject


@pytest.fixture
def docker_project():
    project = DockerProject("TestProject")

    mock_container1 = MagicMock()
    mock_container1.get_status.return_value = "Running"
    mock_container1.get_memory_usage.return_value = 512
    mock_container1.get_cpu_usage.return_value = 0.2
    mock_container1.get_restarts.return_value = 1
    mock_container1.get_uptime.return_value = 100
    mock_container1.get_open_ports.return_value = {"80", "443"}
    mock_container1.get_short_info.return_value = "Container1 info"

    mock_container2 = MagicMock()
    mock_container2.get_status.return_value = "Stopped"
    mock_container2.get_memory_usage.return_value = 256
    mock_container2.get_cpu_usage.return_value = 0.1
    mock_container2.get_restarts.return_value = 2
    mock_container2.get_uptime.return_value = 50
    mock_container2.get_open_ports.return_value = {"8080"}
    mock_container2.get_short_info.return_value = "Container2 info"

    project.containers = [mock_container1, mock_container2]
    return project, mock_container1, mock_container2


def test_get_status_emoji(docker_project):
    project, c1, c2 = docker_project
    assert project.get_status_emoji() == "🟡"

    c1.get_status.return_value = "Stopped"
    assert project.get_status_emoji() == "🔴"

    c1.get_status.return_value = "Running"
    c2.get_status.return_value = "Running"
    assert project.get_status_emoji() == "🟢"


def test_get_memory_usage(docker_project):
    project, _, _ = docker_project
    assert project.get_memory_usage() == 768


def test_get_cpu_usage(docker_project):
    project, _, _ = docker_project
    assert project.get_cpu_usage() == pytest.approx(0.3)


def test_get_restarts(docker_project):
    project, _, _ = docker_project
    assert project.get_restarts() == 3


def test_get_uptime(docker_project):
    project, _, _ = docker_project
    assert project.get_uptime() == 50


def test_get_open_ports(docker_project):
    project, _, _ = docker_project
    ports = project.get_open_ports()
    assert ports == ["80", "443", "8080"]


def test_get_short_info(docker_project):
    project, _, _ = docker_project
    text = project.get_short_info()
    assert "TestProject" in text
    assert "🟡" in text
    assert "RAM" in text
    assert "CPU" in text


def test_get_info(docker_project):
    project, _, _ = docker_project
    text = project.get_info()
    assert "TestProject" in text
    assert "Container1 info" in text
    assert "Container2 info" in text


def test_get_memory_used_text(docker_project):
    project, _, _ = docker_project
    text = project.get_memory_used_text()
    assert "0.00 MB" in text
