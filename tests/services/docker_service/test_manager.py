from unittest.mock import MagicMock, patch

import pytest

from src.services.docker.manager import DockerManager


@pytest.fixture
def mock_docker_client():
    mock_client = MagicMock()
    mock_container1 = MagicMock()
    mock_container1.name = "container1"
    mock_container1.attrs = {"Config": {"Labels": {"com.docker.compose.project": "projA"}}}

    mock_container2 = MagicMock()
    mock_container2.name = "container2"
    mock_container2.attrs = {"Config": {"Labels": {}}}

    mock_client.containers.list.return_value = [mock_container1, mock_container2]
    mock_client.info.return_value = {"MemTotal": 8 * 1024**3}

    return mock_client


@pytest.fixture
def docker_manager(mock_docker_client):
    with patch("src.services.docker.manager.docker.from_env", return_value=mock_docker_client):
        dm = DockerManager()
    return dm


def test_update_projects_creates_projects_and_containers(docker_manager):
    dm = docker_manager

    with patch("src.services.docker.manager.DockerProject") as MockProject:
        mock_project_a = MagicMock()
        mock_project_b = MagicMock()
        MockProject.side_effect = lambda name: {"Proja": mock_project_a, "Container2": mock_project_b}.get(
            name, MagicMock()
        )

        dm.update_projects()

        assert "Proja" in dm.project_dict
        assert "Container2" in dm.project_dict

        assert mock_project_a.add_container.called
        assert mock_project_b.add_container.called

        assert "container1" in dm.containers_dict
        assert "container2" in dm.containers_dict


def test_get_open_ports(docker_manager):
    dm = docker_manager
    mock_container1 = MagicMock()
    mock_container1.get_open_ports.return_value = {"80", "443"}
    mock_container2 = MagicMock()
    mock_container2.get_open_ports.return_value = {"22"}

    dm.containers_dict = {"c1": mock_container1, "c2": mock_container2}

    ports = dm.get_open_ports()
    assert ports == ["22", "80", "443"]


def test_sorted_projects_puts_running_and_heavy_first(docker_manager):
    dm = docker_manager
    stopped = MagicMock(running_count=MagicMock(return_value=0), get_memory_usage=MagicMock(return_value=0))
    light = MagicMock(running_count=MagicMock(return_value=1), get_memory_usage=MagicMock(return_value=10))
    heavy = MagicMock(running_count=MagicMock(return_value=2), get_memory_usage=MagicMock(return_value=99))
    dm.project_dict = {"A": stopped, "B": light, "C": heavy}

    assert [key for key, _ in dm.sorted_projects()] == ["C", "B", "A"]


def test_update_stats(docker_manager):
    dm = docker_manager
    c1 = MagicMock()
    c2 = MagicMock()
    dm.containers_dict = {"1": c1, "2": c2}

    dm.update_stats()

    c1.update_stats.assert_called_once()
    c2.update_stats.assert_called_once()


def test_get_project_and_container_by_key(docker_manager):
    dm = docker_manager
    p = MagicMock()
    c = MagicMock()
    dm.project_dict = {"key1": p}
    dm.containers_dict = {"cont1": c}

    assert dm.get_project_by_key("key1") is p
    assert dm.get_project_by_key("nope") is None
    assert dm.get_container_by_key("cont1") is c
    assert dm.get_container_by_key("nope") is None


def test_str_representation(docker_manager):
    dm = docker_manager
    dm.project_dict = {"A": MagicMock(), "B": MagicMock()}
    text = str(dm)
    assert text.startswith("<DockerManager")
