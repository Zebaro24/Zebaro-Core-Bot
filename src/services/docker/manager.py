import logging
from concurrent.futures import ThreadPoolExecutor

import docker

from src.services.docker.container import DockerContainer
from src.services.docker.project import DockerProject
from src.utils.format_memory import format_memory

logger = logging.getLogger("docker.manager")


class DockerManager:
    def __init__(self) -> None:
        self.client = docker.from_env()
        self.project_dict: dict[str, DockerProject] = {}
        self.containers_dict: dict[str, DockerContainer] = {}

    def update_projects(self) -> None:
        self.project_dict = {}
        self.containers_dict = {}
        containers_list = self.client.containers.list(all=True)
        logger.debug("Found %d containers", len(containers_list))

        for c in containers_list:
            labels = c.attrs.get("Config", {}).get("Labels", {})
            project_name = labels.get("com.docker.compose.project") or c.name
            project_name = project_name.title()

            if project_name not in self.project_dict:
                self.project_dict[project_name] = DockerProject(project_name)

            docker_container = self.project_dict[project_name].add_container(c)
            self.containers_dict[c.name] = docker_container

        logger.info("Projects updated: %s", list(self.project_dict.keys()))

    def update_stats(self) -> None:
        with ThreadPoolExecutor(max_workers=32) as executor:
            executor.map(lambda c: c.update_stats(), self.containers_dict.values())
        logger.debug("Stats updated for %d containers", len(self.containers_dict))

    def get_open_ports(self) -> list[str]:
        ports: set[str] = set()
        for c in self.containers_dict.values():
            ports.update(c.get_open_ports())
        return sorted(ports, key=int)

    def get_memory_total(self) -> int:
        return int(self.client.info()["MemTotal"])

    def get_memory_used(self) -> float:
        return sum(c.get_memory_usage() for c in self.containers_dict.values())

    def get_memory_used_text(self) -> str:
        return (
            f"💾 Используется {format_memory(self.get_memory_used())}"
            f"/{format_memory(self.get_memory_total())} оперативки\n"
        )

    def get_project_by_key(self, key: str) -> DockerProject | None:
        return self.project_dict.get(key)

    def get_container_by_key(self, key: str) -> DockerContainer | None:
        return self.containers_dict.get(key)

    def __str__(self) -> str:
        return f"<DockerManager {list(self.project_dict.values())}>"
