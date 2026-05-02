import logging
from datetime import UTC, datetime
from html import escape

from docker.models.containers import Container

from src.utils.format_memory import format_memory
from src.utils.format_time import format_duration

# TODO: HTML methods (get_short_info, get_info) should ideally live in
#       interfaces/tg/formatters/docker.py to keep services free of presentation logic.

logger = logging.getLogger("docker.container")


class DockerContainer:
    def __init__(self, container: Container) -> None:
        self.container = container
        self.stats: dict | None = None

    def get_name(self) -> str:
        return str(self.container.name)

    def get_status(self) -> str:
        return str(self.container.status).title()

    def get_status_emoji(self) -> str:
        status_map = {
            "running": "🟢",
            "restarting": "🔄",
            "paused": "⏸️",
        }
        return status_map.get(self.container.status, "🔴")

    def reload(self) -> None:
        self.container.reload()

    def update_stats(self) -> None:
        self.stats = self.container.stats(stream=False)
        logger.debug("Stats updated for container %s", self.get_name())

    def get_memory_usage(self) -> float:
        if not self.stats:
            self.update_stats()
        if not self.stats or not self.stats["memory_stats"]:
            return 0.0
        memory_usage = float(self.stats["memory_stats"]["usage"])
        cache = float(self.stats["memory_stats"]["stats"].get("cache", 0))
        return memory_usage - cache

    def get_cpu_usage(self) -> float:
        if not self.stats:
            self.update_stats()
        if not self.stats or not self.stats["memory_stats"]:
            return 0.0
        cpu_delta = (
            self.stats["cpu_stats"]["cpu_usage"]["total_usage"] - self.stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = self.stats["cpu_stats"]["system_cpu_usage"] - self.stats["precpu_stats"]["system_cpu_usage"]
        per_cpu = self.stats["cpu_stats"]["cpu_usage"].get("percpu_usage")
        cpu_count = len(per_cpu) if per_cpu else 1
        if system_delta > 0 and cpu_delta > 0:
            return float(cpu_delta / system_delta) * cpu_count * 100
        return 0.0

    def get_restarts(self) -> int:
        return int(self.container.attrs["RestartCount"])

    def get_uptime(self) -> int:
        if self.container.status != "running":
            return 0
        started_at = self.container.attrs["State"]["StartedAt"]
        started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return int((datetime.now(UTC) - started_dt).total_seconds())

    def get_open_ports(self) -> set[str]:
        ports = self.container.attrs["NetworkSettings"].get("Ports", {})
        if not ports:
            return set()
        open_ports: set[str] = set()
        for mappings in ports.values():
            if not mappings:
                continue
            for mapping in mappings:
                if host_port := mapping.get("HostPort"):
                    open_ports.add(host_port)
        return open_ports

    def get_short_info(self) -> str:
        text = f"<b>📦 {self.get_name().title()}</b>\n"
        text += f"⚡️ Status: {self.get_status_emoji()} {self.get_status()}\n"
        text += f"💾 RAM: {format_memory(self.get_memory_usage())} | 🖥️ CPU: {(self.get_cpu_usage() * 100):.2f}%\n"
        text += f"🔁 Restarts: {self.get_restarts()}\n"
        if uptime_str := format_duration(self.get_uptime()):
            text += f"⏱️ Uptime: {uptime_str}\n"
        if ports := self.get_open_ports():
            text += f"🌐 Open ports: {', '.join(ports)}\n"
        return text

    def get_info(self) -> str:
        text = self.get_short_info()
        logs_escaped = escape(self.container.logs(tail=20).decode())
        text += f"\n<b>Logs:</b>\n<pre>{logs_escaped}</pre>"
        return text

    def get_short_log(self) -> str:
        return str(self.container.logs(tail=20).decode())

    def start(self) -> None:
        logger.info("Starting container %s", self.get_name())
        self.container.start()

    def stop(self) -> None:
        logger.info("Stopping container %s", self.get_name())
        self.container.stop()

    def restart(self) -> None:
        logger.info("Restarting container %s", self.get_name())
        self.container.restart()

    def __str__(self) -> str:
        return f"<DockerContainer {self.get_name()} {self.get_status()}>"

    def __repr__(self) -> str:
        return self.__str__()
