---
name: push
description: Send committed work to GitHub. Runs the gate, mints a one-shot approval, pushes. Triggered by the owner saying "push" — never on your own initiative.
user-invocable: true
allowed-tools: Bash, Read
---

Pushing is the first of two ways work leaves this machine. It runs CI. It does **not**
deploy — nothing reaches the server without a version tag.

Trigger: the owner says **push** (or `/push`). Never push because it seemed like a good
moment.

## The steps

1. **Show what is about to go out:** `git log origin/main..HEAD --oneline` and `git status`.
2. **`/gate`** — full gate. Red → stop and report. The approval is only ever minted over
   a green gate; that is the entire value of it.
3. **Mint the approval:** `python scripts/approve.py --push`. One-shot, 15 minutes.
   `guard-git` refuses a push without it, including one typed by hand.
4. **Push:** `git push origin main`.
5. **Report** what went out and that CI is running. Offer `gh run list --limit 3` — do not
   sit and poll it.

## When it refuses

- **"git push уходит наружу и требует одобрения"** — step 3 was skipped or the marker
  expired. Re-run the gate and mint again; do not work around the guard.
- **Rejected, remote is ahead** — `git pull --rebase origin main`, gate, push again.
  Never `--force`: `guard-git` blocks it, and on a single-author repository a force-push
  destroys history for no reason.

> Deploying is a different skill with a different approval: `/release`.
