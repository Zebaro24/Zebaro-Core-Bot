---
name: approve-push
description: Mint the one-shot marker that lets a single git push through. Used inside /push after a green gate — rarely needed on its own.
user-invocable: true
allowed-tools: Bash
---

`guard-git` refuses `git push` unless a fresh approval marker exists. This mints it:

```bash
python scripts/approve.py --push
```

One-shot, expires in 15 minutes, consumed by the first push. That expiry is the point: an
approval earned by yesterday's green gate must not be spendable on today's unreviewed
change.

**Only ever mint it over a green gate.** Minting first and checking later inverts the
arrangement — the marker is evidence that the checks passed, not a way around them.

Normally `/push` does this. Reach for it alone only when a push failed after the marker
was consumed (rejected, then rebased) and the gate is still green from a minute ago.

> Deploying uses a different marker and a different skill: `/release`.
