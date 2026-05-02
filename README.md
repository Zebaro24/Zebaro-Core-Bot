# Zebaro-Core-Bot

[![Project Status](https://img.shields.io/badge/Status-Development-yellow)]()
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Playwright](https://img.shields.io/badge/Playwright-1.58-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-4.4-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)

Multi-platform automation bot: Telegram, Discord, FastAPI webhooks, Docker control, GitHub alerts, job scraping.

> ⚠️ The project is currently under active development.

---

## Features

**Telegram Bot (Aiogram 3)**
- Admin utilities: chat ID, server health, MongoDB stats
- Docker control: list/start/stop/restart containers and projects
- Service manager: enable/disable services and infrastructure at runtime via `/services`
- Job notifications: scheduled digests from multiple sources

**Discord Bot (discord.py)**
- Commands and events with activity presence
- Can be toggled on/off at runtime (requires bot restart)

**Webhooks API (FastAPI + Uvicorn)**
- GitHub webhook handling (push, PR, workflow, releases)
- Telegram webhook mode for production
- Routes under `/webhook/github` and `/webhook/telegram`

**Job Search & Scraping**
- Headless browsing via Playwright Stealth (remote browser server)
- Sources: Work.ua, Robota.ua, NoFluffJobs, Jooble, Djinni, DOU

**Infrastructure management**
- MongoDB and Playwright containers started/stopped on demand
- Cascade logic: disabling infrastructure disables dependent services
- State persisted across restarts in `services.json`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Bots | Aiogram 3 (Telegram), discord.py 2 |
| Web | FastAPI + Uvicorn |
| Scraping | Playwright + playwright-stealth + BeautifulSoup4 |
| Scheduler | APScheduler |
| Docker | docker SDK for Python |
| Database | MongoDB (PyMongo) |
| Config | pydantic-settings |
| Tooling | Poetry, black, isort, flake8, mypy, bandit |
| Testing | pytest, pytest-asyncio, pytest-cov |

---

## Installation & Setup

**1. Clone**
```bash
git clone https://github.com/Zebaro24/Zebaro-Core-Bot.git
cd Zebaro-Core-Bot
```

**2. Install dependencies**
```bash
poetry install
```

**3. Create `.env`**
```dotenv
# Required
TELEGRAM_BOT_TOKEN=xxxxx:yyyyy
TELEGRAM_ADMIN_ID=123456789
TELEGRAM_DOCKER_ACCESS_IDS=123456789,987654321
DISCORD_BOT_TOKEN=your-discord-bot-token
PERSONAL_GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PERSONAL_GITHUB_SECRET=your-github-webhook-secret
WEBHOOK_URL=https://your-domain.tld

# Optional (have defaults)
DEBUG=false
MONGO_URI=mongodb://localhost:27017/zebaro_core
PLAYWRIGHT_WS_ENDPOINT=ws://localhost:9222
MONGODB_CONTAINER_NAME=zebaro-core-db
PLAYWRIGHT_CONTAINER_NAME=zebaro-core-playwright
```

`TELEGRAM_DOCKER_ACCESS_IDS` — comma-separated Telegram user IDs allowed to manage Docker.

---

## Quick Start (Docker Compose)

```bash
docker compose up -d
```

Starts three containers:
- `zebaro-core-db` — MongoDB
- `zebaro-core-playwright` — Playwright browser server
- `zebaro-core-bot` — bot + webhooks on port 8000 (configurable via `SERVER_PORT`)

---

## Running Locally

```bash
# Start MongoDB and Playwright (or use docker compose for just those)
docker compose up zebaro-core-db zebaro-core-playwright -d

# Run the bot
poetry run python -m src.main
```

The webhooks API is available at `http://127.0.0.1:8000`.

---

## Testing

```bash
poetry run pytest
```

With coverage:
```bash
poetry run pytest --cov=src --cov-report=term-missing
```

---

## Code Quality

```bash
poetry run bandit -r src
poetry run safety check
poetry run black src tests
poetry run isort src tests
poetry run flake8 src tests
poetry run mypy src tests
```

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | Telegram Bot API token |
| `TELEGRAM_ADMIN_ID` | yes | — | Telegram user ID for admin commands |
| `TELEGRAM_DOCKER_ACCESS_IDS` | yes | — | Comma-separated IDs for Docker control |
| `DISCORD_BOT_TOKEN` | yes | — | Discord bot token |
| `PERSONAL_GITHUB_TOKEN` | yes | — | GitHub API token |
| `PERSONAL_GITHUB_SECRET` | yes | — | Webhook HMAC secret |
| `WEBHOOK_URL` | yes | — | Public base URL for webhooks |
| `MONGO_URI` | no | `mongodb://localhost:27017/zebaro_core` | MongoDB connection string |
| `PLAYWRIGHT_WS_ENDPOINT` | no | `ws://localhost:9222` | Playwright browser WebSocket URL |
| `DEBUG` | no | `false` | Polling mode when `true`, webhook mode when `false` |

---

## Contact

- Developer: Denys Shcherbatyi
- Email: zebaro.work@gmail.com

## License

MIT — see [LICENSE](./LICENSE).
