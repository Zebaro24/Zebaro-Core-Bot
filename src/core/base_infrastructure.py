from abc import ABC, abstractmethod


class BaseInfrastructure(ABC):
    name: str
    display_name: str

    @property
    @abstractmethod
    def container_name(self) -> str: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def check_health(self) -> bool: ...
