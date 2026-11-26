---
paths:
  - 'src/services/**'
  - 'src/core/**'
  - 'src/db/**'
  - 'src/infrastructure/**'
  - 'src/scheduler/**'
  - 'migrations/**'
  - 'docker-compose.yml'
  - 'Dockerfile'
---

# Services, storage, infrastructure

```
services/
  docker/         DockerManager, DockerProject, DockerContainer
  github/         the GitHub App: api (JWT, installation token), events (payload → event, pure), store (SQL:
                  repos, levels, forum topics, live messages), service (receive → deliver, given by tg/main.py)
  job_searcher/   container, extract, filter (tiers), cv (3 CVs: routing, fit), letters, keywords, dedup,
                  stats, digest, parser, urls, listeners/, home (PC proxy + noon alert), search_window
                  (LinkedIn), repair (one-off at enable); Jobs API: jobs_api, status (writes), reasons,
                  events (by=event), journal (SQL), silence (S3), backfill
  site_contact.py zebaro.dev contact form: model + rate limit (POST /site/contact)
  notify.py       Claude's notifications: model + SQL records of live messages (/notify, tg/notification/notify.py)
  spotify/        family plan: monobank client, sync, ledger (pure), schedule, report
  vpn/            wg-easy API client, addresses 10.0.0.x, profiles, traffic, installer/ (EXE)
  speedtest/      SpeedTestManager (speed.cloudflare.com over httpx)
```

- **GitHub**: one App webhook for every repo of the account, no hook per repo; the service never imports an
  interface — Telegram delivery is `tg/notification/github.py`, HTML `tg/formatters/github.py`.
- **Vacancy status**: every write (API, buttons, the bot) goes through
  `services/job_searcher/status.py:write_status` — one CAS update + `history` event; Telegram follows
  via `tg_sync` (`tg/notification/job_status.py`), never inside the write. Design: `docs/design/status-write.md`.
- **CVs**: `services/job_searcher/cv.py` (skills, titles, salaries) and `letters.py` mirror the owner's
  CVs in `D:\Work\Career\CV\Upload` and the letters in `Job-Search/cover-letters.md` — a CV or letter
  edit there is an edit here.
- **ServiceManager**: singleton with cascade logic — disabling infra disables dependent services;
  disabling all consumers disables the infra. State in `services.json` (path from
  `SERVICES_STATE_FILE`; in Docker `state/services.json`, because a bind-mounted missing file turns into
  a directory). Scheduler jobs are paused/resumed by the service, not removed.
- **Playwright**: the Python package in `poetry.lock` and the image in `docker-compose.yml` move
  together (major.minor) — `tests/test_playwright_version.py` checks it.
- **VPN**: wg-easy runs with `network_mode: host` (10.0.0.1 = the server), API on `172.17.0.1:51821`
  (the bot reaches it as `host.docker.internal`); the bot owns wg-easy's firewall hooks (`HOOK_POST_UP`
  in `services/vpn/client.py`): `iptables-nft`, because `iptables` in the image is legacy and the host
  is nftables, plus a DROP that keeps VPN peers off the panel. `GET /api/client/{id}` has no
  handshake/traffic: read clients from the list. `WG_VERSION` in `services/vpn/installer.py` and
  `ARG WG_VERSION` in `Dockerfile` move together — `tests/test_vpn_installer_version.py`. `install.bat`
  is shipped with CRLF (built in code).
- **SQL**: new storage goes to SQLAlchemy models + an Alembic revision (`migrations/`,
  `render_as_batch` for SQLite); the bot upgrades to head at start; `tests/services/spotify` checks
  migrations match the models. Money in kopecks, time as Unix int.
- **The Jobs API and `/site/contact` are contracts** (consumers: MCP, the site): a change starts in
  `../docs/contracts.md` — this side first, then the consumer.
