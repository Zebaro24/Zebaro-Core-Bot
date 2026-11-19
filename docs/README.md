---
owns: The index of docs/ — which page owns which subject, and which code each page documents.
not:  How to work here (the workspace's .claude/docs/) · the subjects themselves (the pages below)
---

# Zebaro-Core-Bot — documentation

Grep the **Code** column for a source path to find the page that documents it.

| Page | Owns | Code |
| ---- | ---- | ---- |
| `operations.md` | Gate flags, review focus, tests, commits, release, production | `scripts/**`, `.github/workflows/**` |
| `contracts/jobs-api.md` | The Jobs API — owned here, mirrored in Zebaro-Core-MCP | the jobs interface and service |
| `contracts/notify.md` | The Notify API the Claude harness calls | `src/services/notify.py` |
| `design/status-write.md` | Analysis of status writes (Jobs API, part B) | — |

A big document is a folder: one section per file, the folder's `README.md` is its index.
