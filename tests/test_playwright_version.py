import re
from importlib.metadata import version
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_playwright_server_matches_client_version():
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    client = ".".join(version("playwright").split(".")[:2])

    image = re.search(r"mcr\.microsoft\.com/playwright:v(\d+\.\d+)", compose)
    server = re.search(r"npx playwright@(\d+\.\d+)", compose)

    assert image and server
    assert image.group(1) == client, "docker-compose Playwright image != Python playwright from poetry.lock"
    assert server.group(1) == client, "docker-compose run-server version != Python playwright from poetry.lock"


def test_playwright_server_listens_beyond_its_own_container():
    # Since 1.63 run-server binds to localhost by default: the bot could not reach it at all.
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    command = re.search(r"npx playwright@[\d.]+ run-server[^\n]*", compose)

    assert command and "--host 0.0.0.0" in command.group(0)
