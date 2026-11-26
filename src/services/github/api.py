"""The GitHub App "Zebaro Core Bot": the only code that talks to api.github.com.

The App is installed on the owner's account for all repositories, so one webhook brings every repo's events
and no hook is ever created per repo. Requests run as the installation (a token from the App's JWT, renewed
before it expires); the App's own endpoints (webhook deliveries) take the JWT itself.
"""

import base64
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

logger = logging.getLogger("services.github.api")

API = "https://api.github.com"
TIMEOUT = 10.0
# An installation token lives an hour; it is renewed this long before that.
TOKEN_MARGIN = 300


class GithubApiError(Exception):
    pass


@dataclass(frozen=True)
class Repo:
    full_name: str
    private: bool
    archived: bool


class GithubApp:
    def __init__(
        self, app_id: int, key_b64: str, owner: str = "", transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._app_id = app_id
        self._owner = owner.lower()
        try:
            self._key = base64.b64decode(key_b64, validate=True).decode() if key_b64 else ""
        except ValueError:
            # Never the value in the log; a broken key leaves GitHub idle, the bot runs on.
            logger.error("GH_APP_KEY is not base64 of a PEM: GitHub stays off")
            self._key = ""
        self._client = httpx.AsyncClient(
            base_url=API,
            timeout=TIMEOUT,
            transport=transport,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        self._token: str = ""
        self._token_until = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._app_id and self._key)

    async def close(self) -> None:
        await self._client.aclose()

    # ── auth ────────────────────────────────────────────────────────────────────

    def _jwt(self) -> str:
        now = int(time.time())
        # iat a minute back: GitHub refuses a token from "the future" when the clocks drift.
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(self._app_id)}, self._key, algorithm="RS256")

    async def _send(self, method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
        """Every failure — network, timeout, a refusal — is one GithubApiError with no token or body in it."""
        try:
            response = await self._client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        except httpx.HTTPError as e:
            raise GithubApiError(f"{method} {path}: {type(e).__name__}") from None
        if response.status_code >= 400:
            raise GithubApiError(f"{method} {path}: {response.status_code}")
        return response

    async def _app_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.configured:
            raise GithubApiError("the App is not configured")
        try:
            token = self._jwt()
        except (ValueError, TypeError) as e:
            raise GithubApiError(f"the App's key does not sign: {type(e).__name__}") from None
        return await self._send(method, path, token, **kwargs)

    async def _installation_token(self) -> str:
        if self._token and time.time() < self._token_until - TOKEN_MARGIN:
            return self._token
        installations = (await self._app_request("GET", "/app/installations")).json()
        # Only the owner's installation: another account's must never be used, even if the App were public.
        mine = [i for i in installations if str((i.get("account") or {}).get("login", "")).lower() == self._owner]
        if not mine:
            raise GithubApiError("the App is not installed on the owner's account")
        token = (await self._app_request("POST", f"/app/installations/{mine[0]['id']}/access_tokens")).json()
        self._token = str(token.get("token") or "")
        if not self._token:
            raise GithubApiError("GitHub gave no installation token")
        self._token_until = time.time() + 3600
        return self._token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self._send(method, path, await self._installation_token(), **kwargs)

    # ── what the bot asks ───────────────────────────────────────────────────────

    async def repos(self) -> list[Repo]:
        """Every repository the installation sees, by name."""
        found: list[Repo] = []
        page = 1
        while True:
            data = (
                await self._request("GET", "/installation/repositories", params={"per_page": 100, "page": page})
            ).json()
            items = data.get("repositories", [])
            found += [Repo(str(r.get("full_name", "")), bool(r.get("private")), bool(r.get("archived"))) for r in items]
            if len(items) < 100:
                return sorted(found, key=lambda r: r.full_name.lower())
            page += 1

    async def failed_step(self, repo: str, run_id: int) -> str | None:
        """`job · step` of the first failure in a run, for the one line that says where it broke."""
        jobs = (await self._request("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs")).json().get("jobs", [])
        for job in jobs:
            if job.get("conclusion") != "failure":
                continue
            for step in job.get("steps") or []:
                if step.get("conclusion") == "failure":
                    return f"{job.get('name', '')} · {step.get('name', '')}"
            return str(job.get("name") or "") or None
        return None

    async def rerun_failed(self, repo: str, run_id: int) -> None:
        await self._request("POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs")

    async def redeliver_missed(self, since: float) -> int:
        """Ask GitHub again for every delivery since `since` that did not reach the bot (it was restarting)."""
        deliveries = (await self._app_request("GET", "/app/hook/deliveries", params={"per_page": 100})).json()
        delivered = {d["guid"] for d in deliveries if 200 <= int(d.get("status_code") or 0) < 300}
        sent = 0
        for d in deliveries:
            when = d.get("delivered_at") or ""
            if d["guid"] in delivered or d.get("redelivery") or _epoch(when) < since:
                continue
            try:
                await self._app_request("POST", f"/app/hook/deliveries/{d['id']}/attempts")
                sent += 1
            except GithubApiError as e:
                logger.info("Delivery %s not redelivered: %s", d["id"], e)
        return sent


def _epoch(iso: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
