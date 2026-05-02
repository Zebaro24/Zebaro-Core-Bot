import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.base_infrastructure import BaseInfrastructure
    from src.core.base_service import BaseService

logger = logging.getLogger("core.service_manager")

_STATE_FILE = Path("services.json")


class ServiceManager:
    _instance: "ServiceManager | None" = None

    def __init__(self) -> None:
        self._services: dict[str, "BaseService"] = {}
        self._infrastructure: dict[str, "BaseInfrastructure"] = {}
        self._state: dict = {"infrastructure": {}, "services": {}}

    @classmethod
    def get_instance(cls) -> "ServiceManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Registration ────────────────────────────────────────────────────────

    def register_service(self, service: "BaseService") -> None:
        self._services[service.name] = service
        self._state["services"].setdefault(service.name, True)

    def register_infrastructure(self, infra: "BaseInfrastructure") -> None:
        self._infrastructure[infra.name] = infra
        self._state["infrastructure"].setdefault(infra.name, True)

    # ── State persistence ────────────────────────────────────────────────────

    def load_state(self) -> None:
        if _STATE_FILE.exists():
            try:
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                self._state["infrastructure"].update(data.get("infrastructure", {}))
                self._state["services"].update(data.get("services", {}))
                logger.info("State loaded from %s", _STATE_FILE)
            except Exception as e:
                logger.warning("Failed to load state file, using defaults: %s", e)

    def save_state(self) -> None:
        try:
            _STATE_FILE.write_text(
                json.dumps(self._state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save state file: %s", e)

    # ── Query ────────────────────────────────────────────────────────────────

    def is_service_enabled(self, name: str) -> bool:
        return bool(self._state["services"].get(name, True))

    def is_infra_enabled(self, name: str) -> bool:
        return bool(self._state["infrastructure"].get(name, True))

    def get_services_for_infra(self, infra_name: str) -> list[str]:
        return [s.name for s in self._services.values() if infra_name in s.infra_deps]

    def get_infra_for_service(self, service_name: str) -> list[str]:
        svc = self._services.get(service_name)
        return list(svc.infra_deps) if svc else []

    @property
    def all_services(self) -> dict[str, "BaseService"]:
        return self._services

    @property
    def all_infrastructure(self) -> dict[str, "BaseInfrastructure"]:
        return self._infrastructure

    # ── Health checks ────────────────────────────────────────────────────────

    async def check_infra_health(self, name: str) -> bool:
        infra = self._infrastructure.get(name)
        if infra is None:
            return False
        try:
            return await infra.check_health()
        except Exception:
            return False

    # ── Enable / disable ─────────────────────────────────────────────────────

    async def enable_infrastructure(self, name: str) -> None:
        infra = self._infrastructure.get(name)
        if infra is None:
            logger.error("Unknown infrastructure: %s", name)
            return
        logger.info("Enabling infrastructure: %s", name)
        await infra.start()
        self._state["infrastructure"][name] = True
        self.save_state()

    async def disable_infrastructure(self, name: str) -> None:
        infra = self._infrastructure.get(name)
        if infra is None:
            logger.error("Unknown infrastructure: %s", name)
            return
        # Cascade: disable all dependent services first
        for svc_name in self.get_services_for_infra(name):
            if self.is_service_enabled(svc_name):
                logger.info("Cascade: disabling service %s (infra %s going down)", svc_name, name)
                await self._disable_service_only(svc_name)
        logger.info("Disabling infrastructure: %s", name)
        await infra.stop()
        self._state["infrastructure"][name] = False
        self.save_state()

    async def enable_service(self, name: str) -> None:
        svc = self._services.get(name)
        if svc is None:
            logger.error("Unknown service: %s", name)
            return
        # Enable required infrastructure first
        for infra_name in svc.infra_deps:
            if not self.is_infra_enabled(infra_name):
                logger.info("Enabling infra %s required by service %s", infra_name, name)
                await self.enable_infrastructure(infra_name)
        logger.info("Enabling service: %s", name)
        await svc.on_enable()
        self._state["services"][name] = True
        self.save_state()

    async def disable_service(self, name: str) -> None:
        await self._disable_service_only(name)
        # Cascade: stop infra if no other enabled service needs it
        svc = self._services.get(name)
        if svc:
            for infra_name in svc.infra_deps:
                if self.is_infra_enabled(infra_name):
                    still_needed = any(
                        self.is_service_enabled(s) for s in self.get_services_for_infra(infra_name) if s != name
                    )
                    if not still_needed:
                        logger.info("Cascade: disabling infra %s (no more services need it)", infra_name)
                        await self._stop_infra_only(infra_name)
        self.save_state()

    async def _disable_service_only(self, name: str) -> None:
        svc = self._services.get(name)
        if svc is None:
            logger.error("Unknown service: %s", name)
            return
        logger.info("Disabling service: %s", name)
        await svc.on_disable()
        self._state["services"][name] = False

    async def _stop_infra_only(self, name: str) -> None:
        infra = self._infrastructure.get(name)
        if infra is None:
            return
        logger.info("Stopping infrastructure: %s", name)
        await infra.stop()
        self._state["infrastructure"][name] = False

    # ── Apply saved state on startup ─────────────────────────────────────────

    async def apply_state(self) -> None:
        """Apply the loaded state to infrastructure containers and services.

        If a container fails to start, its state is corrected to False and saved,
        so the UI always reflects reality.
        """
        state_changed = False

        for name, infra in self._infrastructure.items():
            enabled = self._state["infrastructure"].get(name, True)
            try:
                if enabled:
                    await infra.start()
                else:
                    await infra.stop()
            except Exception as e:
                logger.warning("Failed to apply infra state for %s: %s", name, e)
                if enabled:
                    logger.warning("Marking %s as disabled due to startup failure", name)
                    self._state["infrastructure"][name] = False
                    state_changed = True

        for name, svc in self._services.items():
            enabled = self._state["services"].get(name, True)
            try:
                if enabled:
                    await svc.on_enable()
                else:
                    await svc.on_disable()
            except Exception as e:
                logger.warning("Failed to apply service state for %s: %s", name, e)

        if state_changed:
            self.save_state()
            logger.info("State file updated to reflect actual startup conditions")
