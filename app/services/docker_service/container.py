from datetime import datetime
from datetime import UTC
from html import escape

from docker.models.containers import Container

from app.utils.format_memory import format_memory
from app.utils.format_time import format_duration


class DockerContainer:
    def __init__(self, container: Container):
        self.container = container
        self.stats = None

    def get_name(self):
        return self.container.name

    def get_status(self):
        return self.container.status.title()

    def get_status_emoji(self):
        if self.container.status == "running":
            status = "🟢"
        elif self.container.status == "restarting":
            status = "🔄"
        elif self.container.status == "paused":
            status = "⏸️"
        else:
            status = "🔴"
        return status

    def reload(self):
        self.container.reload()

    def update_stats(self):
        self.stats = self.container.stats(stream=False)

    def get_memory_usage(self) -> float:
        if not self.stats:
            self.update_stats()

        if not self.stats["memory_stats"]:
            return 0

        memory_usage = self.stats["memory_stats"]["usage"]
        cache = self.stats["memory_stats"]["stats"].get("cache", 0)

        return memory_usage - cache

    def get_cpu_usage(self) -> float:
        if not self.stats:
            self.update_stats()

        if not self.stats["memory_stats"]:
            return 0

        cpu_delta = self.stats["cpu_stats"]["cpu_usage"]["total_usage"] - self.stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = self.stats["cpu_stats"]["system_cpu_usage"] - self.stats["precpu_stats"]["system_cpu_usage"]

        per_cpu = self.stats["cpu_stats"]["cpu_usage"].get("percpu_usage")
        cpu_count = len(per_cpu) if per_cpu else 1

        if system_delta > 0 and cpu_delta > 0:
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100
        else:
            cpu_percent = 0.0

        return cpu_percent

    def get_restarts(self) -> int:
        return self.container.attrs["RestartCount"]

    def get_uptime(self) -> int:
        if self.container.status != "running":
            return 0
        started_at = self.container.attrs['State']['StartedAt']
        started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))

        now = datetime.now(UTC)

        uptime = now - started_dt
        return int(uptime.total_seconds())

    def get_short_info(self):
        text = f"<b>📦 {self.get_name().title()}</b>\n"
        text += f"⚡️ Status: {self.get_status_emoji()} {self.get_status()}\n"
        text += f"💾 RAM: {format_memory(self.get_memory_usage())} | 🖥️ CPU: {(self.get_cpu_usage() * 100):.2f}%\n"
        text += f"🔁 Restarts: {self.get_restarts()}\n"
        if uptime_str := format_duration(self.get_uptime()):
            text += f"⏱️ Uptime: {uptime_str}\n"
        return text

    def get_info(self):
        text = self.get_short_info()

        logs = self.container.logs(tail=20).decode()
        logs_escaped = escape(logs)

        text += f"\n<b>Logs:</b>\n<pre>{logs_escaped}</pre>"

        return text

    def start(self):
        self.container.start()

    def stop(self):
        self.container.stop()

    def restart(self):
        self.container.restart()

    def get_short_log(self):
        logs = self.container.logs(tail=20).decode()
        return logs
