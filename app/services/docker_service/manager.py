import docker

from app.services.docker_service.container import DockerContainer
from app.services.docker_service.project import DockerProject


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
        text= "<b>🐳 Docker проекты:</b>\n\n"
        for p_name, project in self.project_dict.items():
            text += f"{project.get_short_info()}\n\n"

        return text

    def get_memory_total(self):
        return self.client.info()["MemTotal"]

    def get_project_by_key(self, key):
        return self.project_dict.get(key)

    def get_container_by_key(self, key):
        return self.containers_dict.get(key)

    def __str__(self):
        return f"<DockerManager {list(self.project_dict.values())}>"

if __name__ == '__main__':
    dm = DockerManager()
    dm.update_projects()
    print(dm.get_projects_info())