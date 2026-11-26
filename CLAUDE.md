# Zebaro-Core-Bot

The owner's all-in-one bot: Telegram (server admin, Docker, job search), Discord, FastAPI for GitHub /
Telegram webhooks and the Jobs API, GitHub notifications. One process, one container on
`server.zebaro.dev`. Telegram texts are Russian (the product's language); the repo is English.

Worked on from the workspace (`../CLAUDE.md`). Name this repo in every call: `git -C Zebaro-Core-Bot …`,
`python Zebaro-Core-Bot/scripts/gate.py`.

| Need                                                          | Where                          |
| ------------------------------------------------------------- | ------------------------------ |
| Gate flags, review focus, tests, commits, release, production | `docs/operations.md`           |
| Rules for services/storage/infra · for Telegram/Discord/webhooks | `.claude/rules/` (load with those paths) |
| What the bot does, env variables                              | `README.md`                    |
| The Jobs API — **owned here**, mirrored in MCP                | `docs/contracts/jobs-api.md`   |
| The Notify API — **owned here**, called by the Claude harness | `docs/contracts/notify.md`     |
| `/site/contact` — **owned here**, mirrored in the site        | `docs/contracts/site-contact.md` |

## Layout

Entry point: `python -m src.main` (`scripts\dev.bat`) — Alembic to head, then `asyncio.gather`: Telegram +
FastAPI (webhooks, Jobs API, `/health`) + optional Discord.

```
src/config.py      pydantic-settings singleton; the version is read from pyproject.toml
src/core/          BaseService / BaseInfrastructure, ServiceManager (state in services.json)
src/db/            sql.py — SQLAlchemy: PostgreSQL in compose, SQLite in tests; Json/UtcDateTime types, kv
src/scheduler/     APScheduler singleton, timezone from TZ
src/infrastructure/ playwright.py — start/stop the browser container
src/services/      docker, github, job_searcher, site_contact, spotify, vpn, speedtest
src/interfaces/    tg (formatters, handlers, notification), ds, webhooks
scripts/           gate.py (= CI), release.py, dev.bat, prod.bat, home_proxy.py (owner's PC)
```

## Rules everywhere

- **HTML for Telegram only in `interfaces/tg/formatters/`**, never in services.
- **DB / Playwright degrade gracefully**: try/except with a fallback, never crash the bot.
- **Scheduler runs in local time** (`TZ`, default `Europe/Berlin`), not UTC.
- **Tests replace `src.config` with a mock at import time** — never read `settings` at module level in
  a way a `MagicMock` breaks.

## Commands

```bat
scripts\dev.bat infra        :: PostgreSQL + Playwright in Docker
scripts\dev.bat              :: the bot locally (DEBUG=True → polling)
scripts\prod.bat health      :: is production alive, which version (no SSH)
```

Known TODOs: `ds/commands/help.py` needs content; `event_handler.py` — `workflow_run` both branches do
the same thing.
