---
name: release
description: Deploy Zebaro-Core-Bot to the production server — strict gate, CHANGELOG, version bump, tag, confirmation, push. Triggered by the owner saying "release" or "deploy". The model never tags or deploys on its own.
user-invocable: true
allowed-tools: Bash, Read, Edit, Write
---

Pushing a `vX.Y.Z` tag is the only thing that reaches production: CD runs the gate,
builds the image, pushes it to GHCR and runs `docker compose up -d` on
`server.zebaro.dev`. So this is slow on purpose, and it ends with the owner's go.

Trigger: the owner says **release** or **deploy** (or gave that permission explicitly for
this task).

## The steps

1. **Agree the scope.** `git log $(git describe --tags --abbrev=0)..HEAD --oneline`, and
   the bump: `patch` (fixes), `minor` (features), `major` (breaking). Say which you would
   pick and why; the owner decides.

2. **Write `## Unreleased` in `CHANGELOG.md`** if it is empty — Russian, what changed for
   the owner as a user of the bot, not a list of commits. Commit it
   (`docs(changelog): ...`). `release.py` refuses to run with an empty section: notes are
   written before the tag, because fixing them after means re-pointing a deployed tag.

3. **Strict gate:** `python scripts/gate.py --strict`. Red → stop.

4. **Preview:** `python scripts/release.py --bump <kind> --dry-run`.

5. **Prepare:** `python scripts/release.py --bump <kind>` — VERSION, mirrors in
   `pyproject.toml` and `src/config.py`, stamps the CHANGELOG section, commits
   `chore(release): vX.Y.Z`, tags locally, mints both approvals. **It does not push.**

6. **Ask for the final go**, unless it was already given for this task. Say plainly: the
   bot container restarts, Telegram and Discord are offline for a few seconds.

7. **Ship:** `git push origin main`, then `git push origin vX.Y.Z`. The tag push starts CD.

8. **Watch it land.** `gh run list --limit 3`; when CD is green:

   ```
   scripts\prod.bat health      :: {"status":"ok","version":"X.Y.Z"} — the new version answers
   scripts\prod.bat ps          :: fresh uptime on zebaro-core-bot
   scripts\prod.bat logs zebaro-core-bot 10m
   ```

   A green CD with the old version in `/health` means the container was not recreated.

9. **Report** the version, what is in it, and the health result.

## If it goes wrong

Roll forward, not back: fix, `--bump patch`, release again. Moving a tag backwards leaves
the server on an image nobody can reproduce from history.
