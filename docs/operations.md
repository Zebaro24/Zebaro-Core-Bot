---
owns: How this repo is checked, reviewed, tested, released and looked after in production — the specifics the workspace's generic skills and agents need.
not:  What the bot does (README.md) · the always-on code rules (CLAUDE.md) · the Jobs API (docs/contracts/jobs-api.md)
---

# Operations

The workspace (`../CLAUDE.md`) owns the workflow, the guards and the skills. This page is what they
need to know about this repo.

## Gate

`scripts/gate.py` is this repo's own (not the template's) — the same command CI and the first step of
CD run. From the workspace root: `python Zebaro-Core-Bot/scripts/gate.py …`.

```bash
python scripts/gate.py            # everything (~15 s), exactly as CI
python scripts/gate.py --lint     # lint and types while working
python scripts/gate.py --tests    # tests only
python scripts/gate.py --strict   # + coverage, before a release
python scripts/gate.py --fix      # ruff check --fix + ruff format, then the gate
python scripts/gate.py --only pytest -- tests/interfaces/test_telegram_webhook.py
```

`pip-audit` replaced `safety check` (it needs an account now and failed silently in CI). Red without a
single edit → a new advisory: `poetry update <package>`; if a dependency pins the old version, check
whether a newer parent releases it (aiogram 3.31 released `aiohttp`).

## Review focus (code-reviewer)

1. **Correctness at the boundaries:** an empty result, MongoDB down, the Playwright container stopped,
   Telegram flood control, the same handler running twice at once, a scheduled run overlapping a
   manual one.
2. **This repo's rules** (`CLAUDE.md`, `.claude/rules/`), most often broken in good faith: HTML outside
   `interfaces/tg/formatters/`; class-level state in `GithubManager`; `settings` read at import time;
   DB / Playwright calls that crash instead of degrading; a webhook handler doing long work inline;
   scheduler times in UTC; Playwright versions out of step.
3. **Tests:** a fix without a test that would have caught the bug is incomplete.

## Tests (test-writer)

- **Many modules read `settings` or open MongoDB at import time.** Tests replace those modules first:

  ```python
  sys.modules["src.config"] = MagicMock(settings=mock_settings)
  sys.modules["src.db.client"] = MagicMock(jobs_collection=MagicMock(), start_db=AsyncMock())
  ```

  Follow the neighbouring test file; never read a `settings` attribute at module level in a way a
  `MagicMock` breaks (`Path(settings.x)`) — read it lazily.
- Async: `@pytest.mark.asyncio`, `AsyncMock`. A side effect that must wait is an `async def`, not a
  lambda returning a coroutine (an un-awaited coroutine + `filterwarnings = error` fails the test).
- No network, no Docker, no real Telegram. Listener parsers run on saved HTML snippets.
- The job filter: table-driven cases — a title and description in, a moderation and a score out.

| What                                        | Where                                       |
| ------------------------------------------- | ------------------------------------------- |
| Job search: listeners, filter, dedup, stats | `tests/services/job_searcher/`              |
| Docker, GitHub                              | `tests/services/docker_service/`, `github/` |
| Webhook routes, Telegram delivery           | `tests/interfaces/`                         |
| Repo-wide invariants (versions in sync)     | `tests/test_*.py`                           |

## Commits and versions

- Scopes: `jobs` · `tg` · `webhooks` · `docker` · `github` · `ds` · `infra` · `deps` · `tooling` ·
  `changelog`. The word "AI" is allowed in messages: AI/ML vacancies are this bot's subject.
- One version, in `pyproject.toml`: `src/config.py` reads it (served by `/health`), `release.py` bumps
  it there. The `vX.Y.Z` tag is the only thing that deploys.
- **CHANGELOG** is written **before** a release, under `## Unreleased`: what changed for the owner as a
  user of the bot, in English from now on (earlier entries stay as they are). `release.py` stamps the
  section with the version and date and refuses an empty one.
- Dependencies: Poetry, `poetry.lock` committed (the gate checks it matches). The `playwright` package
  and the `mcr.microsoft.com/playwright` image move together (a test checks major.minor).

## Release

`/release` from the workspace, with these specifics:

1. `## Unreleased` empty → write it first and commit it (`docs(changelog): …`).
2. `python Zebaro-Core-Bot/scripts/gate.py --strict`.
3. `python Zebaro-Core-Bot/scripts/release.py --bump <kind> --dry-run`, then without `--dry-run`:
   one step — bumps `pyproject.toml`, stamps the CHANGELOG, commits `chore(release): vX.Y.Z`, tags.
   It does not push; the markers it mints are the repo's own and the workspace guard ignores them.
4. `python scripts/approve.py release` at the workspace root (needs the owner's word "release") — a
   call of its own, never chained to step 3: the auto-mode classifier refuses that chain whole.
5. Tell the owner: the bot container restarts, Telegram and Discord are offline for a few seconds.
6. `git -C Zebaro-Core-Bot push origin main`, then `git -C Zebaro-Core-Bot push origin vX.Y.Z` — CD.
7. `gh run list --limit 3`; when CD is green: `scripts\prod.bat health` must show the **new** version
   (`{"status":"ok","version":"X.Y.Z"}`), `prod.bat ps` a fresh uptime, `prod.bat logs zebaro-core-bot 10m`.
   A green CD with the old version means the container was not recreated → `gh run rerun <id>`.

Roll forward, never back: re-pushing an old `v*` tag runs CD and deploys **old** code (if history must
be rewritten, the owner disables CD first: `gh workflow disable CD`).

## Production

One VPS: `zebaro@server.zebaro.dev`, compose in `/srv/zebaro-core`, containers `zebaro-core-bot`,
`zebaro-core-db` (MongoDB 4.4), `zebaro-core-playwright` (browser server), `zebaro-core-vpn`
(wg-easy); public `https://bot.zebaro.dev`. Use `scripts\prod.bat`, not long `ssh` lines.

```bat
scripts\prod.bat health                     :: public HTTP only — needs no permission
scripts\prod.bat ps                         :: containers and uptime          (SSH: ask first)
scripts\prod.bat logs                       :: bot logs, last 24h
scripts\prod.bat logs zebaro-core-playwright 1h
scripts\prod.bat state                      :: which services are switched on
```

- **Logs start at the last container recreation.** A deploy erases them; the job history lives in
  MongoDB (`jobs`).
- `Update id=… is handled. Duration N ms` — one Telegram update; updates run in the background. If
  `query is too old` shows up again, something blocks the event loop with a synchronous call.
- `Playwright version mismatch` → `docker-compose.yml` and `poetry.lock` disagree.
- `/services` all on again after a restart → `prod.bat state`; the file is
  `/srv/zebaro-core/state/services.json`.
- **Never print a container's environment** (`docker inspect` without `--format`, `docker exec … env`):
  it holds every bot token.
- Never edit files on the server, restart containers or write to the database unless the owner asked
  for that exact action. Production changes through `/release`; a hand-fix disappears at the next
  deploy.
