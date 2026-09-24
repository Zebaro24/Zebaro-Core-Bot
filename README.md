# Zebaro-Core-Bot

[![Project Status](https://img.shields.io/badge/Status-Development-yellow)]()
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Playwright](https://img.shields.io/badge/Playwright-1.59-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-4.4-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)

Multi-platform automation bot: Telegram, Discord, FastAPI webhooks, Docker control, GitHub alerts, job scraping.

> ⚠️ The project is currently under active development.

---

## Features

**Telegram Bot (Aiogram 3)**
- Admin utilities: chat ID, server health, MongoDB stats
- Docker control: `/server_status` — projects and containers as tables, two-column paged buttons, start/stop/restart, logs
- VPN: `/vpn` — WireGuard (wg-easy) clients with online status and traffic; add with a chosen address (`10.0.0.<n>`), enable/disable, access expiry, rename, readdress, delete; sends two named profiles (full / LAN) or a one-file Windows installer
- Service manager: enable/disable services and infrastructure at runtime via `/services`
- Job notifications: scheduled digests from multiple sources, stats on demand via `/job_stats`

**Discord Bot (discord.py)**
- Commands and events with activity presence
- Can be toggled on/off at runtime (requires bot restart)

**Webhooks API (FastAPI + Uvicorn)**
- GitHub webhook handling (push, PR, workflow, releases)
- Telegram webhook mode for production
- Routes under `/webhook/github` and `/webhook/telegram`; public `/jobs/r/<id>` (click-tracked vacancy links) and `/health`
- `POST /site/contact` — zebaro.dev's contact form → a Telegram message with a reply button; bearer token, compose network only (404 through the public tunnel), 5 messages an hour per sender
- Telegram updates are answered at once and handled in the background

**Job Search & Scraping**
- Headless browsing via Playwright Stealth (remote browser server, full Chromium in new headless mode)
- Sources: Work.ua, Robota.ua, NoFluffJobs, Djinni, DOU, HappyMonday, BazaIT, Wellfound (Jooble is behind a bot challenge; Work.ua vacancy pages too, so Work.ua vacancies carry the list snippet)
- Work.ua, Robota.ua and HappyMonday block the server's datacenter IP; with `HOME_PROXY_URL` they go through the owner's PC over the VPN — `python scripts/home_proxy.py` there (stdlib only: CONNECT :443, only the server's address, only with the login)
- Relevance scoring, apply / not-interested buttons, cross-site duplicate marks, weekly digest

**VPN (WireGuard via wg-easy)**
- `zebaro-core-vpn` runs wg-easy in the host network: `10.0.0.1` is the server itself (Samba, the home PC at `10.0.0.2`)
- Addresses: `.2–.9` the owner's devices, `.10–.99` chosen per person, `.100+` automatic; DNS is AdGuard (ads blocked)
- The Windows installer is a 7-Zip SFX: installs WireGuard 1.1.1 only when missing or older, imports `Zebaro-<Name>` and `Zebaro-<Name>-LAN`, switches one on unless another VPN is active
- Traffic history survives counter resets (Mongo); first-connection and access-expiry notices; weekly table on Fridays

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
| Tooling | Poetry, black, isort, flake8, mypy, bandit, pip-audit — all through `scripts/gate.py` |
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
```bash
cp .env.example .env   # names of every variable; fill in the values
```

`TELEGRAM_DOCKER_ACCESS_IDS` — comma-separated Telegram user IDs allowed to manage Docker.

---

## Quick Start (Docker Compose)

```bash
docker compose up -d
```

Starts four containers:
- `zebaro-core-db` — MongoDB
- `zebaro-core-playwright` — Playwright browser server
- `zebaro-core-bot` — bot + webhooks on port 8000 (configurable via `SERVER_PORT`)
- `zebaro-core-vpn` — wg-easy (WireGuard, UDP 51820; API on the Docker bridge only); needs `WG_PASSWORD`

---

## Running Locally

```bat
scripts\dev.bat infra   :: MongoDB + Playwright in Docker (needs docker-compose.override.yml for ports)
scripts\dev.bat         :: the bot: poetry run python -m src.main
```

With `DEBUG=True` the Telegram bot uses polling; the webhooks API is on `http://127.0.0.1:8000`.

---

## Quality Gate

One command runs every check — the same one CI runs and CD runs before deploying:

```bash
python scripts/gate.py            # poetry-lock, black, isort, flake8, mypy, bandit, pip-audit, pytest
python scripts/gate.py --lint     # fast: lint and types only
python scripts/gate.py --strict   # tests with coverage
python scripts/gate.py --fix      # apply black + isort first
```

See `scripts/README.md` for the release and production helpers.

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
| `WEBHOOK_URL` | yes | — | Public base URL for webhooks and vacancy links |
| `JOB_STATS_API_TOKEN` | no | empty (endpoints refuse) | Bearer token for `/jobs/stats/weekly` and `/jobs/review` |
| `SITE_CONTACT_TOKEN` | no | empty (endpoint refuses) | Shared with zebaro.dev (`CONTACT_TOKEN` there) for `/site/contact` |
| `WG_PASSWORD` | yes for compose | — | wg-easy admin password (12+ chars); the bot gets it as `WG_EASY_PASSWORD` |
| `HOME_PROXY_URL` | no | empty (boards go direct) | `http://user:pass@10.0.0.2:8899` — HTTP proxy on the owner's PC in the VPN; Work.ua, Robota.ua and HappyMonday are opened through it (they block the server's IP) and skipped in 2 s when it is off |
| `WG_HOST` | no | `server.zebaro.dev` | Endpoint clients connect to; must resolve straight to the server (no Cloudflare proxy) |
| `TZ` | no | `Europe/Berlin` | Scheduler timezone (and log time in Docker) |
| `SERVICES_STATE_FILE` | no | `services.json` | Where `/services` toggles are saved |
| `MONGO_URI` | no | `mongodb://localhost:27017/zebaro_core` | MongoDB connection string |
| `PLAYWRIGHT_WS_ENDPOINT` | no | `ws://localhost:9222` | Playwright browser WebSocket URL |
| `DEBUG` | no | `false` | Polling mode when `true`, webhook mode when `false` |

---

## Contact

- Developer: Denys Shcherbatyi
- Email: zebaro.work@gmail.com

## License

MIT — see [LICENSE](./LICENSE).
