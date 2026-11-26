import base64
import sys
from unittest.mock import AsyncMock, MagicMock

if "src.config" not in sys.modules:
    sys.modules["src.config"] = MagicMock(settings=MagicMock())
if "src.db.client" not in sys.modules:
    sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.services.github.api import GithubApiError, GithubApp

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


class Fake:
    """GitHub's API as far as the App uses it; records who asked with which token."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.deliveries: list[dict] = []
        self.jobs: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        path = request.url.path
        self.calls.append((request.method, path, token))
        if path == "/app/installations":
            claims = jwt.decode(token, KEY.public_key(), algorithms=["RS256"])
            assert claims["iss"] == "77"
            return httpx.Response(200, json=[{"id": 5}])
        if path == "/app/installations/5/access_tokens":
            return httpx.Response(201, json={"token": "inst-token"})
        if path == "/installation/repositories":
            page = int(request.url.params["page"])
            names = [f"o/r{i}" for i in range(100)] if page == 1 else ["o/archived"]
            return httpx.Response(200, json={"repositories": [
                {"full_name": n, "private": n == "o/r1", "archived": n == "o/archived"} for n in names]})  # fmt: skip
        if path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": self.jobs})
        if path == "/app/hook/deliveries":
            return httpx.Response(200, json=self.deliveries)
        if path.endswith("/attempts") or path.endswith("/rerun-failed-jobs"):
            return httpx.Response(202, json={})
        return httpx.Response(404)


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def app(fake):
    return GithubApp(77, base64.b64encode(PEM).decode(), transport=httpx.MockTransport(fake))


@pytest.mark.asyncio
async def test_repos_page_through_with_one_installation_token(app, fake):
    repos = await app.repos()
    assert len(repos) == 101 and repos[0].full_name == "o/archived" and repos[0].archived
    assert [r.private for r in repos if r.full_name == "o/r1"] == [True]
    tokens = [c for c in fake.calls if c[1] == "/app/installations/5/access_tokens"]
    assert len(tokens) == 1
    assert all(c[2] == "inst-token" for c in fake.calls if c[1] == "/installation/repositories")


@pytest.mark.asyncio
async def test_the_failed_step_names_job_and_step(app, fake):
    steps = [{"name": "setup", "conclusion": "success"}, {"name": "mypy", "conclusion": "failure"}]
    fake.jobs = [
        {"name": "lint", "conclusion": "success", "steps": []},
        {"name": "gate", "conclusion": "failure", "steps": steps},
    ]
    assert await app.failed_step("o/r", 1) == "gate · mypy"


@pytest.mark.asyncio
async def test_only_missed_deliveries_are_asked_for_again(app, fake):
    fake.deliveries = [
        {"id": 1, "guid": "a", "status_code": 502, "delivered_at": "2026-11-26T10:00:00Z", "redelivery": False},
        {"id": 2, "guid": "a", "status_code": 200, "delivered_at": "2026-11-26T10:05:00Z", "redelivery": True},
        {"id": 3, "guid": "b", "status_code": 0, "delivered_at": "2026-11-26T10:01:00Z", "redelivery": False},
        {"id": 4, "guid": "c", "status_code": 502, "delivered_at": "2020-01-01T00:00:00Z", "redelivery": False},
    ]
    since = 1795600000.0  # 2026-11-25
    assert await app.redeliver_missed(since) == 1
    assert [c[1] for c in fake.calls if c[1].endswith("/attempts")] == ["/app/hook/deliveries/3/attempts"]


@pytest.mark.asyncio
async def test_a_refusal_is_an_error_not_a_crash(app, fake):
    with pytest.raises(GithubApiError):
        await app._request("GET", "/nowhere")


def test_without_a_key_the_app_is_not_configured():
    assert not GithubApp(0, "").configured
