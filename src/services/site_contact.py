"""A message from the contact form on zebaro.dev.

The model lives here, not in the route, so the Telegram formatter can use it without
importing the web layer.
"""

from collections import deque
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SiteContact(BaseModel):
    # The same bounds the site validates with; the site has already trimmed the strings.
    name: str = Field(min_length=2, max_length=80)
    reply: str = Field(min_length=3, max_length=120)  # e-mail, @handle, phone or a link
    message: str = Field(min_length=10, max_length=2000)
    locale: Literal["en", "uk"] = "en"
    sender: str = Field(pattern=r"^[0-9a-f]{16}$")  # sha256(IP)[:16] — never the IP itself
    sentAt: datetime  # noqa: N815 — the site's field name


class ContactRateLimit:
    """Second line of defence: the site already limits per IP. One process, so memory is enough."""

    def __init__(self, window_s: float = 3600, per_sender: int = 5, overall: int = 30) -> None:
        self.window_s = window_s
        self.per_sender = per_sender
        self.overall = overall
        self._recent: deque[tuple[float, str]] = deque()

    def allow(self, sender: str, now: float) -> bool:
        while self._recent and now - self._recent[0][0] > self.window_s:
            self._recent.popleft()
        if len(self._recent) >= self.overall:
            return False
        if sum(1 for _, seen in self._recent if seen == sender) >= self.per_sender:
            return False
        self._recent.append((now, sender))
        return True

    def reset(self) -> None:
        self._recent.clear()
