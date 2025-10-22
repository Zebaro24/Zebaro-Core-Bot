from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.docker_service.container import DockerContainer


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.name = "test_container"
    container.status = "running"
    container.attrs = {
        "RestartCount": 3,
        "State": {"StartedAt": datetime.now(UTC).isoformat()},
        "NetworkSettings": {
            "Ports": {
                "80/tcp": [{"HostPort": "8080"}],
                "22/tcp": None,
            }
        },
    }
    container.stats.return_value = {
        "memory_stats": {"usage": 2048000, "stats": {"cache": 1024000}},
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200000000, "percpu_usage": [1, 1, 1, 1]},
            "system_cpu_usage": 5000000000,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100000000},
            "system_cpu_usage": 4000000000,
        },
    }
    container.logs.return_value = b"test log line 1\ntest log line 2"
    return container


@pytest.fixture
def docker_container(mock_container):
    return DockerContainer(mock_container)


def test_get_name(docker_container):
    assert docker_container.get_name() == "test_container"


def test_get_status(docker_container):
    assert docker_container.get_status() == "Running"


def test_get_status_emoji_running(docker_container):
    assert docker_container.get_status_emoji() == "🟢"


def test_get_memory_usage(docker_container):
    result = docker_container.get_memory_usage()
    assert result == 1024000.0  # usage - cache


def test_get_cpu_usage(docker_container):
    cpu_percent = docker_container.get_cpu_usage()
    assert isinstance(cpu_percent, float)
    assert cpu_percent > 0


def test_get_restarts(docker_container):
    assert docker_container.get_restarts() == 3


def test_get_uptime(docker_container):
    uptime = docker_container.get_uptime()
    assert isinstance(uptime, int)
    assert uptime >= 0


def test_get_open_ports(docker_container):
    ports = docker_container.get_open_ports()
    assert ports == {"8080"}


@patch("app.services.docker_service.container.format_duration")
@patch("app.services.docker_service.container.format_memory")
def test_get_short_info(mock_format_memory, mock_format_duration, docker_container):
    mock_format_memory.return_value = "0.99 MB"
    mock_format_duration.return_value = "5 min"

    text = docker_container.get_short_info()
    assert "Status:" in text
    assert "RAM: 0.99 MB" in text
    assert "Restarts: 3" in text
    assert "Uptime: 5 min" in text
    assert "Open ports: 8080" in text


def test_get_info(docker_container):
    text = docker_container.get_info()
    assert "<b>Logs:</b>" in text
    assert "test log line 1" in text


def test_start_stop_restart(docker_container):
    docker_container.start()
    docker_container.container.start.assert_called_once()  # noqa

    docker_container.stop()
    docker_container.container.stop.assert_called_once()  # noqa

    docker_container.restart()
    docker_container.container.restart.assert_called_once()  # noqa


def test_get_short_log(docker_container):
    log_text = docker_container.get_short_log()
    assert "test log line 1" in log_text
    assert isinstance(log_text, str)
