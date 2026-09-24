import logging
from concurrent.futures import ThreadPoolExecutor

from docker.models.containers import Container

from src.services.docker.container import DockerContainer, port_sort_key

logger = logging.getLogger("docker.project")


class DockerProject:
    def __init__(self, name: str) -> None:
        self.name = name
        self.containers: list[DockerContainer] = []

    def add_container(self, container: Container) -> DockerContainer:
        docker_container = DockerContainer(container)
        self.containers.append(docker_container)
        return docker_container

    def reload_containers(self) -> None:
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(lambda c: c.reload(), self.containers)

    def update_stats(self) -> None:
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(lambda c: c.update_stats(), self.containers)

    def sorted_containers(self) -> list[DockerContainer]:
        return sorted(self.containers, key=lambda c: (not c.is_running(), c.get_name()))

    def running_count(self) -> int:
        return sum(1 for c in self.containers if c.is_running())

    def get_status_emoji(self) -> str:
        count_disabled = len(self.containers) - self.running_count()
        if count_disabled == len(self.containers):
            return "🔴"
        if count_disabled > 0:
            return "🟡"
        return "🟢"

    def get_memory_usage(self) -> float:
        return sum(c.get_memory_usage() for c in self.containers)

    def get_cpu_usage(self) -> float:
        return sum(c.get_cpu_usage() for c in self.containers)

    def get_restarts(self) -> int:
        return sum(c.get_restarts() for c in self.containers)

    def get_uptime(self) -> int:
        uptimes = [c.get_uptime() for c in self.containers if c.get_uptime() > 0]
        return min(uptimes) if uptimes else 0

    def get_open_ports(self) -> list[str]:
        ports: set[str] = set()
        for c in self.containers:
            ports.update(c.get_open_ports())
        return sorted(ports, key=port_sort_key)

    def __str__(self) -> str:
        return f"<DockerProject {self.name} {self.containers}>"

    def __repr__(self) -> str:
        return self.__str__()
