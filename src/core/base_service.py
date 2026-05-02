from abc import ABC, abstractmethod


class BaseService(ABC):
    name: str  # unique key, e.g. "job_searcher"
    display_name: str  # human-readable, e.g. "Job Searcher"
    infra_deps: list[str]  # infrastructure names this service depends on
    needs_restart: bool = False  # True if toggle requires bot restart

    @abstractmethod
    async def on_enable(self) -> None:
        """Called when service is enabled at runtime."""

    @abstractmethod
    async def on_disable(self) -> None:
        """Called when service is disabled at runtime."""
