---
name: playbook
description: Open the Zebaro-Core-Bot playbook — how the workflow, gate, commits, deploy and guards work. Use when a step is unclear, a situation is non-standard, or a guard blocked something.
user-invocable: true
allowed-tools: Read
---

The deep "how to work here" documentation lives in `.claude/docs/`. `CLAUDE.md` is always
loaded and stays thin; this is the depth. Read **only** the page the question needs.

| Question                                                  | Page                          |
| --------------------------------------------------------- | ----------------------------- |
| What next · the automatic loop · push vs deploy           | `.claude/docs/workflow.md`    |
| Commits · gate · versions and tags · language · `.env`    | `.claude/docs/conventions.md` |
| A guard blocked something · CI red · prod looks wrong     | `.claude/docs/faq.md`         |

Answer concisely from the page and cite the file. If nothing covers it, say so plainly —
that gap is worth a line in `.claude/docs/faq.md`.
