---
name: gate
description: Run the Zebaro-Core-Bot quality gate and report a compact pass/fail table. Runs automatically when a change is finished, before any commit.
user-invocable: true
allowed-tools: Bash, Read
---

One checker, one command. Never call black / isort / flake8 / mypy / bandit / pip-audit /
pytest by hand — a green that CI did not produce is not a green.

1. **Pick the scope from where you are**, not from habit:

   | Situation                               | Command                                 |
   | --------------------------------------- | --------------------------------------- |
   | while working, quick feedback           | `python scripts/gate.py --lint`         |
   | a change is done, before the commit     | `python scripts/gate.py`                |
   | before a release (this is what CI runs) | `python scripts/gate.py --strict`       |
   | touched dependencies                    | `python scripts/gate.py --security`     |
   | one test                                | `--only pytest -- tests/path::test_name` |

2. **Formatting red?** `python scripts/gate.py --fix` applies black and isort, then run the
   gate again. That is the reason `--fix` exists: so fixing formatting never needs a
   checker called around the gate.

3. **Relay the result as it printed.** Do not summarise a red as "почти зелено".

4. **Fix the reds, then run again.** A failing check is the answer, not an obstacle.
   Loosening a test or silencing a rule to get green converts a caught bug into a
   shipped one — if a rule is genuinely wrong, that is a conversation with the owner.

`pip-audit` needs the network and can turn red on a CVE published today with no change on
our side. That is the point of it: update the package (`poetry update <pkg>`), never
ignore the advisory silently.
