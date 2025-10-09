import docker
from concurrent.futures import ThreadPoolExecutor

from app.services.docker_service.container import DockerContainer
from app.services.docker_service.project import DockerProject
from app.utils.format_memory import format_memory


class DockerManager:
    def __init__(self):
        self.client = docker.from_env()

        self.project_dict: dict[str, DockerProject] = {}
        self.containers_dict: dict[str, DockerContainer] = {}

    def update_projects(self):
        self.project_dict = {}
        containers_list = self.client.containers.list(all=True)

        for c in containers_list:
            labels = c.attrs.get("Config", {}).get("Labels", {})
            project_name = labels.get("com.docker.compose.project")

            if not project_name:
                project_name = c.name

            project_name = project_name.title()

            if project_name not in self.project_dict:
                self.project_dict[project_name] = DockerProject(project_name)

            docker_container = self.project_dict[project_name].add_container(c)
            self.containers_dict[c.name] = docker_container

    def get_projects_info(self):
        self.update_stats()

        text= "<b>🐳 Docker проекты:</b>\n\n"
        for p_name, project in self.project_dict.items():
            text += f"{project.get_short_info()}\n\n"

        text += self.get_memory_used_text()

        return text

    def update_stats(self):
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(lambda c: c.update_stats(), self.containers_dict.values())

    def get_memory_total(self):
        return self.client.info()["MemTotal"]

    def get_memory_used_text(self):
        mem = 0
        for c in self.containers_dict.values():
            mem += c.get_memory_usage()

        text = f"💾 Используется {format_memory(mem)}/{format_memory(self.get_memory_total())} оперативки"
        return text

    def get_project_by_key(self, key):
        return self.project_dict.get(key)

    def get_container_by_key(self, key):
        return self.containers_dict.get(key)

    def __str__(self):
        return f"<DockerManager {list(self.project_dict.values())}>"

if __name__ == '__main__':
    import time

    start = time.perf_counter()

    dm = DockerManager()
    dm.update_projects()

    print(f"Execution time: {time.perf_counter() - start:.6f} секунд")

    container = list(dm.containers_dict.values())[0]
    container.update_stats()
    print(container.get_short_info())

    print(f"Execution time: {time.perf_counter() - start:.6f} секунд")

    start = time.perf_counter()

    print(dm.get_projects_info())

    print(f"Execution time: {time.perf_counter() - start:.6f} секунд")
