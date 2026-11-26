"""GitHub as a service the owner switches in /services: events in, decisions out, Telegram elsewhere.

The webhook route hands every verified event to `receive`; the service parses it and passes the result
to `deliver` — given by tg/main.py, so this module knows no interface. Processing runs in the background:
GitHub waits 10 s for an answer, a Telegram send may take longer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from src.config import settings
from src.core.base_service import BaseService
from src.services.github import store
from src.services.github.api import GithubApp
from src.services.github.events import Event, parse

logger = logging.getLogger("services.github")

Deliver = Callable[[Event], Awaitable[None]]
# A restart is shorter than this; deliveries older than it are not asked for again.
REDELIVER_WINDOW = 2 * 3600
REDELIVER_DELAY = 60
SEEN_DELIVERIES = 500


class GithubService(BaseService):
    name = "github"
    display_name = "GitHub"
    infra_deps: list[str] = []

    def __init__(self, deliver: Deliver, app: GithubApp | None = None) -> None:
        self._deliver = deliver
        self.app = app or GithubApp(settings.gh_app_id, settings.gh_app_key, settings.gh_owner)
        self.owner = str(settings.gh_owner).lower()
        self._seen: deque[str] = deque(maxlen=SEEN_DELIVERIES)
        self._tasks: set[asyncio.Task[None]] = set()
        self._started = time.time()

    @property
    def ready(self) -> bool:
        """Without the App's id and key nothing can be answered or rerun: the webhook refuses (503)."""
        return self.app.configured

    async def on_enable(self) -> None:
        if not self.ready:
            logger.warning("GitHub App is not configured (GH_APP_ID, GH_APP_KEY): the webhook refuses events")
            return
        # Before the first event: an event adds its repo, and the import only runs while nothing is set up.
        await self._import_legacy()
        self._spawn(self._redeliver())
        logger.info("GitHub service enabled")

    async def on_disable(self) -> None:
        logger.info("GitHub service disabled")

    def from_owner(self, payload: dict[str, Any]) -> bool:
        """The event belongs to the owner's account: their repo, or their installation."""
        repo_owner = ((payload.get("repository") or {}).get("owner") or {}).get("login")
        account = ((payload.get("installation") or {}).get("account") or {}).get("login")
        return str(repo_owner or account or "").lower() == self.owner

    def receive(self, delivery: str, event: str, payload: dict[str, Any]) -> bool:
        """Queue one verified delivery; False when it was seen already or is not the owner's account's."""
        if delivery and delivery in self._seen:
            return False
        if not self.from_owner(payload):
            logger.warning("GitHub %s from another account ignored", event)
            return False
        if delivery:
            self._seen.append(delivery)
        parsed = parse(event, payload, self.owner)
        if parsed is not None:
            self._spawn(self._handle(parsed))
        return True

    async def _handle(self, parsed: Event) -> None:
        try:
            await self._deliver(parsed)
        except Exception:
            logger.exception("GitHub event %s not delivered", type(parsed).__name__)

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _import_legacy(self) -> None:
        """The old service's repo → topic list (Mongo), once, so the forum keeps its topics."""
        try:
            from src.db.client import github_notification_collection

            records = await github_notification_collection.find().to_list(length=None)
            imported = await store.import_legacy(records)
            if imported:
                logger.info("Imported %d GitHub repos from the old setup", imported)
        except Exception as e:
            logger.info("Old GitHub setup not imported: %s", e)

    async def _redeliver(self) -> None:
        await asyncio.sleep(REDELIVER_DELAY)
        try:
            sent = await self.app.redeliver_missed(since=self._started - REDELIVER_WINDOW)
            if sent:
                logger.info("Asked GitHub to redeliver %d missed events", sent)
        except Exception as e:
            logger.warning("Missed GitHub deliveries not checked: %s", e)
