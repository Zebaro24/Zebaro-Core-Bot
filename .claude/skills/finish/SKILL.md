---
name: finish
description: Wrap up a finished change — gate, review, docs, then a clean local commit. Runs on its own when the work for a request is done; never asks permission and never pushes.
user-invocable: true
allowed-tools: Bash, Read, Edit, Write
---

Run this **automatically** when the work for the owner's request is complete. Do not
wait to be told, do not ask "закоммитить?". Every finished change ends up gated and
committed with no ceremony, and nothing leaves the machine without a word from the owner.

## The steps

1. **`/gate`** — green. Reds are fixed first. Bugs do not enter history.

2. **Review, sized to the change.** Trivial edit → a careful self-check. Substantial
   change → the **`code-reviewer`** agent; address blockers and majors.

3. **Docs, if behaviour changed.** `CLAUDE.md` (always-on rules and layout), `README.md`
   (features, commands), `.claude/docs/` (process). A rule in `CLAUDE.md` that the code no
   longer follows is worse than no rule. If the change is user-visible, add a line to
   `## Unreleased` in `CHANGELOG.md` — in Russian, about what changed for the owner as a
   user of the bot, not a list of commits.

4. **The "Как проверить" block** — two to four concrete checks the owner can run: a
   command in Telegram, a `curl`, `scripts\prod.bat logs` after a deploy, a targeted test
   through the gate. This block is the deliverable; the commit is bookkeeping.

5. **Commit — never push.** One logical change per commit, one line, English, imperative:
   `type(scope): summary` — e.g. `fix(jobs): wait out flood control instead of dropping
   the batch`. Types: `feat` `fix` `docs` `refactor` `test` `chore` `perf` `ci`. Scopes:
   `jobs` `tg` `webhooks` `docker` `github` `ds` `infra` `deps` `tooling`.
   **No Co-Authored-By, no mention of the assistant or its vendor anywhere** — the author
   of this repository is the human, and `guard-git` refuses anything else.

6. **Tell the owner it is committed**, and that `push` sends it to GitHub and `release`
   deploys it — whenever they want, not now.

> Stop here. `git push` and deploying happen only on the owner's word.
