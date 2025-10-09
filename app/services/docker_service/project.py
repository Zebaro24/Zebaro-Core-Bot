from concurrent.futures import ThreadPoolExecutor

from app.services.docker_service.container import DockerContainer
from app.utils.format_memory import format_memory
from app.utils.format_time import format_duration


class DockerProject:
    def __init__(self, name):
        self.name = name

        self.containers: list[DockerContainer] = []

    def add_container(self, container):
        docker_container = DockerContainer(container)
        self.containers.append(docker_container)
        return docker_container

    def reload_containers(self):
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(lambda c: c.reload(), self.containers)

    def update_stats(self):
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(lambda c: c.update_stats(), self.containers)

    def get_status_emoji(self):
        count_disabled = 0
        for c in self.containers:
            if c.get_status() != "Running":
                count_disabled += 1

        status = "🟢"
        if count_disabled == len(self.containers):
            status = "🔴"
        elif count_disabled > 0:
            status = "🟡"

        return status

    def get_memory_usage(self):
        total_mem = 0
        for c in self.containers:
            total_mem += c.get_memory_usage()
        return total_mem

    def get_cpu_usage(self):
        total_cpu = 0
        for c in self.containers:
            total_cpu += c.get_cpu_usage()
        return total_cpu

    def get_restarts(self):
        restarts = 0
        for c in self.containers:
            restarts += c.get_restarts()
        return restarts

    def get_uptime(self):
        uptime = 0
        for c in self.containers:
            if uptime == 0 or c.get_uptime() < uptime:
                uptime = c.get_uptime()
        return uptime

    def get_short_info(self):
        text = f"<b>🚀 {self.name} {self.get_status_emoji()}</b>\n"
        text += f"💾 RAM: {format_memory(self.get_memory_usage())} | 🖥️ CPU: {(self.get_cpu_usage() * 100):.2f}%\n"
        text += f"🔁 Restarts: {self.get_restarts()}"
        if uptime_str := format_duration(self.get_uptime()):
            text += f" | ⏱️ Uptime: {uptime_str}"
        return text

    def get_info(self):
        text = f"<b>🚀 {self.name} {self.get_status_emoji()}</b>\n\n"

        for container in self.containers:
            text += f"{container.get_short_info()}\n\n"

        text += self.get_memory_used_text()
        return text

    def get_memory_used_text(self):
        mem = 0
        for c in self.containers:
            mem += c.get_memory_usage()

        text = f"💾 Используется {format_memory(mem)} оперативки"
        return text


    def __str__(self):
        return f"<DockerProject {self.name} {self.containers}>"

    def __repr__(self):
        return self.__str__()
