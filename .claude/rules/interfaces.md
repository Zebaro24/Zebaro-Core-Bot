---
paths:
  - 'src/interfaces/**'
---

# Interfaces: Telegram, Discord, webhooks

```
interfaces/
  tg/formatters/        HTML formatting lives HERE (never in services)
  tg/handlers/admin/    admin commands incl. /services, /get_job_openings
  tg/handlers/callbacks/, keyboards/, middlewares/
  tg/notification/      job search run, weekly digest, day's 👀 summary, AI notes per session
  ds/                   discord.py bot + service.py (needs_restart=True)
  webhooks/             FastAPI: /webhook/{github,telegram}, /jobs/* (Jobs API), /site/contact, /notify, /health
```

- **Telegram webhook answers at once**, the update is handled in a background task. Telegram does not
  send the next update until this one is answered — a long handler froze the whole bot. Locally
  (`DEBUG=True`) it is polling; behaviour that differs between the two is a bug.
- **app.state**: `bot`/`dp` set via `webhooks/setup.py`; `github_manager` set by `GithubService.on_enable()`.
- **Discord toggle** requires a bot restart (`needs_restart = True`).
- `webhooks/routes/jobs.py`, `site.py` and `notify.py` (the Claude harness) serve contracts others call — `../docs/contracts.md`.
