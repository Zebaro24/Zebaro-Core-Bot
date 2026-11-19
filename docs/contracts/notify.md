---
owns: The Notify API — what the Claude harness sends to the bot and what it gets back.
not:  How the bot keeps and deletes the messages (src/services/notify.py) · the hook (_Claude-Template: core/.claude/hooks/notify.py)
---

# Notify API — contract

Claude Code's hook (`.claude/hooks/notify.py` of the owner's template, in every project) tells the
owner through the bot that Claude needs them: the task is done, a question, a plan, attention. The
bot keeps **one live message per project** in the owner's chat and deletes it once it is seen.

Owner: the bot. Consumer: the template's `notify.py` — outside this workspace, so there is no mirror;
a change here is a change there in the same session.

## Access

`https://bot.zebaro.dev/notify` — public, through the tunnel: the hook runs on the owner's PC.
`Authorization: Bearer <NOTIFY_API_TOKEN>`. No token, a wrong one, or an unset `NOTIFY_API_TOKEN` on
the bot → `401`, before the body is read.

**Compatibility:** changes only add (fields, `event` values). The bot ignores fields it does not know.

## `POST /notify` — send

```json
{"project": "Zebaro-Core", "repo": "mcp", "event": "plan",
 "title": "план готов", "text": "Нужно твоё «го».", "session": "<Claude session id>"}
```

| Field | Type | Rules |
| --- | --- | --- |
| `project` | string | 1–80; the key of "one live message" |
| `repo` | string \| null | ≤ 80; the workspace repo the session worked in, shown after the project |
| `event` | `done` \| `question` \| `plan` \| `attention` | picks the icon: ✅ ❓ 📋 🔔 |
| `title` | string | 1–80; in the owner's language |
| `text` | string | ≤ 1000, may be empty; the client cuts longer text |
| `session` | string | 1–128; Claude Code's `session_id`, the key of `DELETE` |

The message: `📋 **Zebaro-Core · mcp** — план готов` + the text, with a `✓` button. The project's
previous message is deleted after the new one is sent.

| Status | When |
| --- | --- |
| `202 {"ok": true}` | sent |
| `401` | token |
| `422` | the body does not validate |
| `429` | more than 120 in an hour |
| `503` | the bot is not ready, or Telegram refused (the previous message stays) |

## `DELETE /notify?session=<id>` — the owner answered

Deletes every message of that session. `200 {"deleted": n}`; an unknown session is `{"deleted": 0}`,
not an error. No `session` or longer than 128 → `422`; the bot not ready → `503`.

## Other ways a message goes

- the `✓` button under it;
- 12 hours after it was sent (a sweep every 30 minutes).

The record of live messages is in SQL (`notify_messages`). The database failing → messages are still
sent, but only `✓` removes them.
