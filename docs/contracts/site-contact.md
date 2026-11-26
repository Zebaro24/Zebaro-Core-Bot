---
owns: The site-contact contract — what zebaro.dev's contact form sends to the bot and what it gets back.
not:  How the bot shows the message (src/interfaces/tg/formatters/site_contact.py) · the site's form and its own limits
code: src/interfaces/webhooks/routes/site.py, src/services/site_contact.py
---

# Site contact — contract

zebaro.dev's contact form hands a visitor's message to the bot, which posts it to the owner's Telegram
with a button to reply. The bot owns the Telegram token; the site never sees it.

Owner: the bot. Consumer: Zebaro-Core-Site, `src/features/contact/deliver.ts` — it keeps a verbatim copy
of this file in `docs/contracts/site-contact.md`.

**Compatibility:** changes only add (optional fields, status codes the site already treats as a failure).
The bot ignores fields it does not know, so the site may send a new optional field before the bot reads it.

## Access

- `POST http://zebaro-core-bot:8000/site/contact` — **inside the compose network only**
  (`zebaro-core_default`). A request that came through the public tunnel carries `Cf-Connecting-Ip` and
  gets `404`, before anything else is checked: from outside the endpoint does not exist.
- `Authorization: Bearer <token>` — the site's `CONTACT_TOKEN` = the bot's `SITE_CONTACT_TOKEN`.
  No token, a wrong one, or an unset `SITE_CONTACT_TOKEN` on the bot → `401`, before the body is read.
- The site's `CONTACT_ENDPOINT` is the URL above.

## Body

```json
{"name": "Anna", "reply": "@anna", "message": "Hi! We have a Python role…",
 "locale": "en", "sender": "3f2a9c0d1e4b5a67", "sentAt": "2026-11-26T12:00:00.000Z"}
```

| Field | Type | Rules |
| --- | --- | --- |
| `name` | string | 2–80, trimmed by the site |
| `reply` | string | 3–120: e-mail, `@handle`, phone or a link — the reply button is built from it |
| `message` | string | 10–2000 |
| `locale` | `en` \| `uk` | the page's language; default `en` |
| `sender` | string | `^[0-9a-f]{16}$` — the first 16 hex of sha256 of the visitor's IP, never the IP |
| `sentAt` | ISO 8601 datetime | when the site accepted the form |

## Answers

| Status | When | The site shows |
| --- | --- | --- |
| `202 {"ok": true}` | the Telegram message is sent (inside the request) | sent |
| `401` | token | failed |
| `404` | came through the tunnel | failed |
| `422` | the body does not validate | failed |
| `429` | more than 5 an hour from one `sender`, or 30 an hour overall | limited |
| `503` | the bot is not ready, or Telegram refused the message | failed |

The message itself is never logged on either side — only that delivery failed, and `sender`.
