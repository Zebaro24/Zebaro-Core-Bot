import logging
from concurrent.futures import ThreadPoolExecutor

from docker.models.containers import Container

from src.services.docker.container import DockerContainer
from src.utils.format_memory import format_memory

# TODO: HTML methods (get_short_info, get_info) should ideally live in
#       interfaces/tg/formatters/docker.py to keep services free of presentation logic.

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

    def get_status_emoji(self) -> str:
        count_disabled = sum(1 for c in self.containers if c.get_status() != "Running")
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
        return sorted(ports, key=int)

    def get_memory_used_text(self) -> str:
        return f"💾 Используется {format_memory(self.get_memory_usage())} оперативки"

    def get_short_info(self) -> str:
        from src.utils.format_time import format_duration

        text = f"<b>🚀 {self.name} {self.get_status_emoji()}"
        text += f" | 📦 {len(self.containers)} cont" if len(self.containers) > 1 else ""
        text += "</b>\n"
        text += f"💾 RAM: {format_memory(self.get_memory_usage())} | 🖥️ CPU: {(self.get_cpu_usage() * 100):.2f}%\n"
        text += f"🔁 Restarts: {self.get_restarts()}"
        if uptime_str := format_duration(self.get_uptime()):
            text += f" | ⏱️ Uptime: {uptime_str}"
        if ports := self.get_open_ports():
            text += f"\n🌐 Open ports: {', '.join(ports)}"
        return text

    def get_info(self) -> str:
        text = f"<b>🚀 {self.name} {self.get_status_emoji()}</b>\n\n"
        for container in self.containers:
            text += f"{container.get_short_info()}\n\n"
        text += self.get_memory_used_text()
        return text

    def __str__(self) -> str:
        return f"<DockerProject {self.name} {self.containers}>"

    def __repr__(self) -> str:
        return self.__str__()
