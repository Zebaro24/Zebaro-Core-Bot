# CLAUDE.md

## Project layout

Source code lives in `src/`, not `app/` (old folder can be deleted).
Entry point: `python -m src.main`.

```
src/
├── main.py                   # asyncio.gather: db + tg + webhooks (+ ds if enabled)
├── config.py                 # pydantic-settings singleton: settings
├── core/
│   ├── base_service.py       # BaseService ABC: on_enable / on_disable
│   ├── base_infrastructure.py
│   └── service_manager.py    # Singleton; state persisted to services.json
├── db/                       # MongoDB client + collections
├── scheduler/                # APScheduler singleton
├── infrastructure/           # mongodb.py, playwright.py — start/stop Docker containers
├── services/
│   ├── docker/               # DockerManager, DockerProject, DockerContainer
│   ├── github/               # GithubManager (instance-level dicts!), service, webhook, event_handler
│   ├── job_searcher/         # container, filter, formatter, parser, urls, listeners/
│   └── speedtest/            # SpeedTestManager
├── interfaces/
│   ├── tg/
│   │   ├── formatters/       # HTML formatting lives HERE (not in services)
│   │   ├── handlers/admin/   # admin commands incl. /services
│   │   ├── handlers/callbacks/
│   │   ├── keyboards/
│   │   ├── middlewares/
│   │   └── notification/
│   ├── ds/                   # discord.py bot + service.py (needs_restart=True)
│   └── webhooks/             # FastAPI + uvicorn; routes use request.app.state
└── utils/                    # format_memory, format_time
```

## Key architectural rules

- **HTML formatting**: always in `interfaces/tg/formatters/`, never in services.
- **GithubManager**: instance-level dicts (`github_repo_webhooks`, `github_repo_events`) — NOT class-level.
- **app.state**: `bot`/`dp` set via `webhooks/setup.py`; `github_manager` set by `GithubService.on_enable()`.
- **ServiceManager**: singleton with cascade logic — disabling infra disables dependent services; disabling all consumers disables the infra. State saved to `services.json` (gitignored, runtime file).
- **Discord toggle** requires bot restart (`needs_restart = True`).
- **DB/Playwright resilience**: all operations wrapped in try/except with graceful fallback.

## Quality checks

Run against `src`, not `app`:

```bash
poetry run bandit -r src
poetry run safety check
poetry run black src tests
poetry run isort src tests
poetry run flake8 src tests
poetry run mypy src tests
poetry run pytest
```

## Known TODOs

- `dou.py` / `jooble.py`: hardcoded year in date parsing
- `ds/commands/help.py`: help command needs content
- `event_handler.py`: `workflow_run` both branches do the same thing — review intent
