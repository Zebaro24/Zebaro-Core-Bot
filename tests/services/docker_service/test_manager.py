from unittest.mock import MagicMock, patch

import pytest

from app.services.docker_service.manager import DockerManager


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
    with patch("app.services.docker_service.manager.docker.from_env", return_value=mock_docker_client):
        dm = DockerManager()
    return dm


def test_update_projects_creates_projects_and_containers(docker_manager):
    dm = docker_manager

    with patch("app.services.docker_service.manager.DockerProject") as MockProject:
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


def test_get_memory_used_text(docker_manager):
    dm = docker_manager
    mock_c1 = MagicMock(get_memory_usage=MagicMock(return_value=512 * 1024 * 1024))
    mock_c2 = MagicMock(get_memory_usage=MagicMock(return_value=256 * 1024 * 1024))
    dm.containers_dict = {"a": mock_c1, "b": mock_c2}

    with patch("app.services.docker_service.manager.format_memory", side_effect=lambda x: f"{x/1024**3:.1f}G"):
        dm.get_memory_total = MagicMock(return_value=1024**3)
        text = dm.get_memory_used_text()

    assert "Используется" in text
    assert "0.8G/1.0G" in text


def test_get_projects_info(docker_manager):
    dm = docker_manager
    project1 = MagicMock()
    project1.get_short_info.return_value = "proj info"
    dm.project_dict = {"Proj": project1}
    dm.get_open_ports = MagicMock(return_value=["8080"])
    dm.update_stats = MagicMock()
    dm.get_memory_used_text = MagicMock(return_value="RAM text\n")

    text = dm.get_projects_info()
    assert text.startswith("<b>🐳 Docker проекты:")
    assert "proj info" in text
    assert "RAM text" in text
    assert "8080" in text
    dm.update_stats.assert_called_once()


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
