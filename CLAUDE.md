# Zebaro-Core-Bot

Личный бот-комбайн одного владельца: Telegram-бот (админка сервера, Docker, поиск вакансий),
Discord-бот, FastAPI для вебхуков GitHub/Telegram, уведомления о GitHub. Один процесс,
один контейнер на `server.zebaro.dev`.

Файл тонкий сознательно: каждая строка стоит контекста в каждой сессии. Процесс и
подробности — в `.claude/docs/` (или `/playbook`), что делает бот — в `README.md`.

## Система контроля

Веток и PR нет, работаем в `main`. **По умолчанию всё автоматически, наружу — только по слову.**

- Закончил изменение → сам гоняешь гейт, само-ревью, доки и `CHANGELOG`, делаешь **чистый
  локальный коммит** (`/finish`). Не спрашивай «закоммитить?».
- Владелец сказал **`push`** → `/push`: гейт → одноразовое одобрение → `git push` → CI.
- Владелец сказал **`release`** / **`deploy`** → `/release`: строгий гейт → версия →
  тег `vX.Y.Z` → CD (ещё раз гейт) → сервер.

**Проверки — только `python scripts/gate.py`.** Не зови black / isort / flake8 / mypy /
bandit / pip-audit / pytest руками: проверка мимо гейта — это «зелено», которое не совпадает
с CI. Один тест — `--only pytest -- путь::тест`, форматирование — `--fix`.

**Автор коммитов — человек.** Ни `Co-Authored-By`, ни упоминаний ассистента и его вендора —
нигде: ни в коммитах, ни в тегах, ни в PR, ни в комментариях, ни в документах. Хук
`guard-git` такой коммит блокирует. Формат — одна строка `type(scope): summary`.

**Язык.** Разговор, `CLAUDE.md`, `.claude/docs/`, `CHANGELOG.md`, тексты бота — русский.
Код, комментарии в новом коде, коммиты, теги — английский.

**Прод.** Заход по SSH — действие наружу: спроси перед первым `ssh` в задаче.
`scripts\prod.bat health` бьёт по публичному HTTP и разрешения не требует. На сервере
ничего не меняем руками — только через релиз.

**Заметил постороннее** — баг мимоходом, врущий документ, идею: спроси владельца одной
строкой, делаем сейчас или в заметки. «Нет» → `/idea` → `_ideas/`. Не решай в одиночку.

## Раскладка

Entry point: `python -m src.main` (`scripts\dev.bat`).

```
src/
├── main.py                   # asyncio.gather: db + tg + webhooks (+ ds if enabled)
├── config.py                 # pydantic-settings singleton; version mirrored from VERSION
├── core/
│   ├── base_service.py       # BaseService ABC: on_enable / on_disable
│   ├── base_infrastructure.py
│   └── service_manager.py    # Singleton; state persisted to services.json
├── db/                       # MongoDB (AsyncMongoClient) + collections
├── scheduler/                # APScheduler singleton, timezone from TZ
├── infrastructure/           # mongodb.py, playwright.py — start/stop Docker containers
├── services/
│   ├── docker/               # DockerManager, DockerProject, DockerContainer
│   ├── github/               # GithubManager (instance-level dicts!), service, webhook, event_handler
│   ├── job_searcher/         # container, filter (scoring), dedup, stats, parser, urls, listeners/
│   ├── site_contact.py       # zebaro.dev contact form: model + rate limit
│   ├── vpn/                  # wg-easy API client, addresses 10.0.0.x, profiles, traffic, installer/ (EXE)
│   └── speedtest/            # SpeedTestManager
├── interfaces/
│   ├── tg/
│   │   ├── formatters/       # HTML formatting lives HERE (not in services)
│   │   ├── handlers/admin/   # admin commands incl. /services, /get_job_openings
│   │   ├── handlers/callbacks/
│   │   ├── keyboards/
│   │   ├── middlewares/
│   │   └── notification/     # job search run, weekly digest
│   ├── ds/                   # discord.py bot + service.py (needs_restart=True)
│   └── webhooks/             # FastAPI: /webhook/{github,telegram}, /jobs/*, /site/contact, /health
└── utils/                    # format_memory, format_time
scripts/                      # gate.py, release.py, approve.py, dev.bat, prod.bat, start-claude.bat, home_proxy.py (owner's PC)
.claude/                      # settings.json, hooks/, skills/, agents/, docs/
_ideas/  _temp/               # вне git: находки и черновики
```

## Правила

- **HTML formatting**: always in `interfaces/tg/formatters/`, never in services.
- **GithubManager**: instance-level dicts (`github_repo_webhooks`, `github_repo_events`) — NOT class-level.
- **app.state**: `bot`/`dp` set via `webhooks/setup.py`; `github_manager` set by `GithubService.on_enable()`.
- **Telegram webhook answers at once**, the update is handled in a background task. Telegram does not send the next update until this one is answered — a long handler froze the whole bot.
- **ServiceManager**: singleton with cascade logic — disabling infra disables dependent services; disabling all consumers disables the infra. State in `services.json` (path from `SERVICES_STATE_FILE`; in Docker `state/services.json`, because a bind-mounted missing file turns into a directory).
- **Discord toggle** requires bot restart (`needs_restart = True`).
- **DB/Playwright resilience**: operations wrapped in try/except with graceful fallback.
- **Scheduler runs in local time** (`TZ`, default `Europe/Berlin`), not UTC.
- **Playwright**: the Python package in `poetry.lock` and the image in `docker-compose.yml` move together (major.minor) — `tests/test_playwright_version.py` checks it.
- **VPN**: wg-easy runs with `network_mode: host` (10.0.0.1 = the server), API on `172.17.0.1:51821` (bot reaches it as `host.docker.internal`); the bot owns wg-easy's firewall hooks (`HOOK_POST_UP` in `services/vpn/client.py`): `iptables-nft`, because `iptables` in the image is legacy and the host is nftables, plus a DROP that keeps VPN peers off the panel. `GET /api/client/{id}` has no handshake/traffic: read clients from the list. `WG_VERSION` in `services/vpn/installer.py` and `ARG WG_VERSION` in `Dockerfile` move together — `tests/test_vpn_installer_version.py`. `install.bat` is shipped with CRLF (built in code).
- **Tests replace `src.config` with a mock at import time** — never read `settings` at module level in a way a `MagicMock` breaks.

## Команды

```bash
python scripts/gate.py                 # ЕДИНСТВЕННЫЙ чекер (~15 с), ровно как CI
python scripts/gate.py --lint          # по ходу работы
python scripts/gate.py --strict        # перед релизом: + покрытие
python scripts/gate.py --fix           # black + isort, потом гейт
python scripts/release.py --bump minor --dry-run
```

```bat
scripts\dev.bat infra        :: MongoDB + Playwright в Docker
scripts\dev.bat              :: бот локально (DEBUG=True → polling)
scripts\prod.bat health      :: жив ли прод и какая версия
scripts\prod.bat logs        :: логи бота за сутки
scripts\start-claude.bat     :: открыть Claude Code в корне проекта
```

## Known TODOs

- `ds/commands/help.py`: help command needs content
- `event_handler.py`: `workflow_run` both branches do the same thing — review intent
