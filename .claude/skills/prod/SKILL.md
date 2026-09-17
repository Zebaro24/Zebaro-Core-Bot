---
name: prod
description: Check the production server — health, containers, logs, service state. Use after a deploy, or when something looks wrong in production.
user-invocable: true
allowed-tools: Bash, Read
---

Production is one VPS: `zebaro@server.zebaro.dev`, compose in `/srv/zebaro-core`,
containers `zebaro-core-bot`, `zebaro-core-db` (MongoDB 4.4), `zebaro-core-playwright`
(browser server), public address `https://bot.zebaro.dev`.

Use `scripts\prod.bat` instead of long `ssh` lines.

## Start with the cheap check

```bat
scripts\prod.bat health
```

Public HTTP only — it does not enter the server, so it needs no permission.

## Then, if needed

```bat
scripts\prod.bat ps                               :: containers and uptime
scripts\prod.bat logs                             :: bot logs, last 24h, with timestamps
scripts\prod.bat logs zebaro-core-bot 2h
scripts\prod.bat logs zebaro-core-playwright 1h
scripts\prod.bat state                            :: which services are switched on
```

**SSH is an outward action — ask before the first connection in a task.** `health` is
exempt; everything else is not.

## Reading the answer

- **Logs start at the last container recreation.** A deploy erases earlier lines; a
  restart from `/services` does not. The job history lives in MongoDB (`jobs`), not in logs.
- **`Update id=… is handled. Duration N ms`** is how long a Telegram update took. Updates
  are processed in the background, so a long one no longer blocks the next.
- **`Playwright version mismatch`** means `docker-compose.yml` and `poetry.lock` disagree —
  `tests/test_playwright_version.py` should have caught it.
- **Never print a container's environment** (`docker inspect` without `--format`,
  `docker exec … env`): it holds every bot token. `guard-secrets` refuses it.

## What you never do here

Do not edit files on the server, do not restart or recreate containers, do not touch the
database with anything but reads — unless the owner asked for that specific action in
this conversation. The way to change production is `/release`. A hand-fix on the server
is invisible to git and disappears at the next deploy.
