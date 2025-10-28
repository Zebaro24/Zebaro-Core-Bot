# Zebaro-Core-Bot 🤖

[![Project Status](https://img.shields.io/badge/Status-Development-yellow)]()
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.119.0-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![discord.py](https://img.shields.io/badge/discord.py-2.6.3-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Playwright](https://img.shields.io/badge/Playwright-1.55.0-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-4.4-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)

Zebaro-Core-Bot is a multi-platform automation bot built with Python. It combines a Telegram bot, a Discord bot,
a FastAPI-based webhook service, and a background scheduler. With it you can manage Docker containers, receive
GitHub repository event notifications, scrape and filter job openings from popular sites, and deliver useful updates
right into your chats.

> ⚠️ The project is currently under active development.

---

## ✨ Core Features

- Telegram Bot (Aiogram 3)
  - 👮 Admin utilities: get chat ID, server health checks, MongoDB stats
  - 🐳 Docker control: list/start/stop/restart containers and projects directly from Telegram
  - 🧾 Job notifications: scheduled digests from multiple sources
- Discord Bot (discord.py)
  - 🧩 Commands and events with a rich presence/activity
- Webhooks API (FastAPI + Uvicorn)
  - 🔔 GitHub webhooks handling (repository events)
  - 📬 Telegram webhook mode for production
  - 📡 Endpoints are grouped under `/webhook` (e.g., `/webhook/github`, `/webhook/telegram`)
- Job Search & Scraping
  - 🤖 Headless browsing via Playwright Stealth (connects to an external browser server)
  - 🧠 Parsing with BeautifulSoup
  - 🌍 Sources: Work.ua, Robota.ua, NoFluffJobs, Jooble, Djinni, DOU
- Scheduling
  - ⏰ APScheduler for periodic tasks (e.g., sending job digests)
- Persistence
  - 🍃 MongoDB for data storage
- Development Friendly
  - 🧪 Pytest test suite and clean tooling (black, isort, flake8, mypy)

---

## 🧰 Tech Stack

- Backend: Python 3.11
- Bots: Aiogram 3 (Telegram), discord.py 2.6
- Web Framework: FastAPI + Uvicorn
- Real-time scraping: Playwright (remote browser server) + playwright-stealth
- Parsing: BeautifulSoup4
- Scheduler: APScheduler
- Docker integration: docker SDK for Python
- Database: MongoDB (PyMongo)
- Packaging/Tooling: Poetry, black, isort, flake8, mypy
- Testing: Pytest (+ pytest-asyncio, pytest-cov)

---

## ⚙️ Installation & Setup

1. Clone the repository

   ```bash
   git clone https://github.com/Zebaro24/Zebaro-Core-Bot.git
   cd Zebaro-Core-Bot
   ```

2. Install dependencies with Poetry

   ```bash
   poetry install
   ```

3. Create a .env file with required variables

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
   ```

   Notes:
   - TELEGRAM_DOCKER_ACCESS_IDS is a comma-separated list of Telegram user IDs with Docker control access.
   - By default, MongoDB and the Playwright browser endpoint are expected locally; see Docker Quick Start below.

---

## 🚀 Quick Start (Docker Compose)

This project includes a docker-compose.yml to spin up MongoDB, a Playwright browser server, and the bot + webhooks service.

```bash
# Ensure you exported the required environment variables or created a .env file
docker compose up -d
```

- Services started:
  - MongoDB (zebaro-core-db)
  - Playwright server (zebaro-core-playwright)
  - Core bot + webhooks (zebaro-core-bot) on port 8000 by default

---

## 🧭 Running Locally (without Docker)

1. Start a Playwright browser server (or keep the one from Docker):

   ```bash
   npx playwright@1.55.0 run-server --port 9222
   ```

2. Ensure MongoDB is running locally (or via Docker).

3. Activate the virtual environment and run the app:

   ```bash
   poetry shell
   python -m app.main
   # or
   poetry run python -m app.main
   ```

The webhooks API will be available at http://127.0.0.1:8000, with routes under /webhook.

---

## 🧪 Testing

```bash
poetry run pytest
```

Run all project tests and check functionality.

---

## 🔧 Configuration Reference

- TELEGRAM_BOT_TOKEN: Telegram Bot API token
- TELEGRAM_ADMIN_ID: Your Telegram user ID (for admin-only features)
- TELEGRAM_DOCKER_ACCESS_IDS: Comma-separated Telegram IDs allowed to manage Docker
- DISCORD_BOT_TOKEN: Discord bot token
- PERSONAL_GITHUB_TOKEN: Token used by GitHub integrations
- PERSONAL_GITHUB_SECRET: Webhook secret used to verify GitHub events
- WEBHOOK_URL: Public base URL used for webhooks
- MONGO_URI: Mongo connection string (defaults to mongodb://localhost:27017/zebaro_core)
- PLAYWRIGHT_WS_ENDPOINT: ws URL where the Playwright browser server is exposed (defaults to ws://localhost:9222)
- DEBUG: Run Telegram bot in polling mode when true; webhook mode when false

---

## 📬 Contact

- Developer: Denys Shcherbatyi
- Email: zebaro.work@gmail.com

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.