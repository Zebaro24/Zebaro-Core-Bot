# Jobs API — contract

The Zebaro-Core-Bot bot is the job-search backend. This document is the **single source** for the
client (MCP `zebaro-core-mcp`, tools `jobs_*`): it works with vacancies from this document, without
reading the bot's code. The bot's `/openapi.json` duplicates the response schemas; if they disagree,
this file is right.

- Part **A** — reading: `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/funnel`, `GET /jobs/digest`.
- Part **B** — writing and event analytics: `PATCH /jobs/{id}/status`,
  `POST /jobs/status/batch`, `GET /jobs/reasons`,
  the `history` field in `GET /jobs/{id}`, Telegram message edits, the owner's journal
  (`POST/GET /jobs/journal`), `GET /jobs/funnel?by=event`, rejection by silence. Not shipped yet
  (see "Open"): `PUT /jobs/{id}/ai_verdict`.
- `/jobs/r/{id}` is not part of the API, although it is in `/openapi.json`: the public link behind
  a vacancy's button in Telegram (counts clicks and redirects to the platform), no token.

## General rules

**Address and access.** `https://<host>/jobs...`, header `Authorization: Bearer <JOBS_API_TOKEN>`.
No token or a wrong one → `401` (before any parameter check).

**Compatibility.** One rule: changes **only add** — new fields, new enum values, new parameters,
new endpoints. Nothing is removed or renamed. The client is a tolerant reader: it skips unknown
fields and shows an unknown enum value as is.

**Dates.** ISO 8601 in UTC with `Z`: `2026-10-29T14:03:00Z`. The `from` / `to` parameters take a
date (`2026-10-01` = `2026-10-01T00:00:00Z`) or a date-time; `from` is inclusive, `to` is not.
Example "for October": `from=2026-10-01&to=2026-11-01`.

**Identifier.** `id` is an opaque string. Do not parse it, do not compare it as "greater-less".
The same `id` is in the vacancy's buttons in Telegram.

**Scope (`scope`).** Lists and aggregates carry the field `"scope": "own_searches"`: the data are
vacancies **found by the bot's searches** (its set of platforms and queries), not the market. "More
vacancies about AI" may mean "the searches got wider". Do not draw conclusions about the market
from this data.

**Errors.** Always like this:

```json
{"error": {"code": "invalid_parameter", "message": "limit: 500 is more than 200"}}
```

`message` is written for an LLM reader: which parameter and why.

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_parameter` | unknown parameter value, `from >= to`, `limit` outside 1–200, unknown status, malformed `cursor`; in PATCH — a forbidden status, an unknown field or code, no `evidence` with `actor: ai` |
| 401 | `unauthorized` | no token or a wrong one |
| 404 | `not_found` | no vacancy with this `id` |
| 409 | `status_conflict` | `expected_status` does not match the current one (B); `error` has `current_status` |
| 409 | `is_duplicate` | a status is set on a repeat, the decision lives on another copy (B); `error` has `duplicate_of` |
| 503 | `storage_unavailable` | the database is unavailable; retry later |

An empty period, or a filter nothing matched, is a `200` with an empty list or zeros, not an
error.

## Statuses

One public `status` — where the vacancy is on the path "found → applied → how it ended".

| `status` | Meaning | Set by |
|---|---|---|
| `new` | not decided yet | the bot when found |
| `applied` | applied, no answer yet | owner, AI |
| `replied` | the employer answered | owner, AI |
| `interview` | an interview is scheduled or done | owner, AI |
| `offer` | offer | owner, AI |
| `rejected_by_employer` | rejected by the employer (at any stage after applying) | owner, AI |
| `mismatch` | the owner does not meet the requirements | owner, AI |
| `not_interested` | the owner is not interested | owner, AI |
| `blocked` | the platform does not let the owner apply (Djinni); a copy from another platform will arrive on its own | **only the Telegram button** |
| `duplicate` | a repeat of a vacancy whose decision lives on another copy (`duplicate_of`) | only the bot |

**Reason** — two fields, both optional:

- `status_reason_code` — a code from the status's vocabulary (`GET /jobs/reasons` returns them with
  descriptions):
  - `mismatch`: `experience | location | english | stack | other`;
  - `not_interested`: `role | stack | domain | conditions | position_closed | other | muted`
    (`position_closed` = closed before the owner could apply; `muted` =
    "don't send this company any more", set **only by the button**);
  - `rejected_by_employer`: `no_response | no_reason | position_closed | experience | stack |
    location | work_permit | english | salary | other`. The words are the same as in `mismatch`
    where the meaning is the same: "I don't meet the experience bar myself" and "rejected for
    experience" are comparable. `no_reason` — a template rejection ("we chose another
    candidate"), `no_response` — silence after applying, `work_permit` — no work permit
    (≠ `location`).
  - None fits → `other` + `suggested_code` (which code would fit, `snake_case`) + `reason`.
- `status_reason` — free text (for example, a summary of the rejection email). Always stored, even
  when a code fits.

These are reasons for a **decision** (the owner's or the employer's). Why the bot's filter dropped
a vacancy is a different field, `filter_reason`; list filters: `reason_code` — by
`status_reason_code`, `filter_reason` — by `filter_reason`.

**Filter tier (`tier`)** is a separate axis, not a status: how the bot rated the vacancy when found.

| `tier` | Meaning |
|---|---|
| `top` | exactly the owner's stack, came to Telegram with sound |
| `sent` | fits, came to Telegram |
| `review` | partial match, came in the shared 👀 digest |
| `filtered_out` | the filter dropped it, it did not come to Telegram; why — `filter_reason` |

## Keyword search (list and funnel)

| Parameter | Meaning |
|---|---|
| `any=ai,llm,rag` | has **at least one** of the words |
| `all=python,react` | has **all** the words |
| `none=senior,php` | has **none** of the words |
| `where=title\|description\|both` | where to search, `both` by default |

- Words are comma-separated; a phrase with a space is one word (`any=machine learning`). Up to 20
  words per parameter, each 1 to 50 characters.
- A match is a **whole word, case-insensitive**: the neighbouring character is not a letter or a
  digit. `any=ai` finds "AI Engineer", "AI/ML", "AI-powered", but **not** "email" and not
  "training". Cyrillic the same way: `any=джун` finds «Джун», but not «Джуніор».
- Characters inside a word are literal: `any=c#,next.js,node.js` work as written.
- Parameters combine with AND: `any=ai,llm&none=senior&where=title`.

## Vacancy

Short form (a list item):

| Field | Type | Meaning |
|---|---|---|
| `id` | string | identifier |
| `title` | string | title |
| `company` | string \| null | company; may be `null` when the platform did not show it |
| `source` | string | platform: `Djinni`, `Dou`, `Work.ua`, `Robota.ua`, `LinkedIn`, ... |
| `url` | string | link to the vacancy on the platform |
| `found_at` | datetime | when the bot found it |
| `published_at` | datetime \| null | publication date on the platform, if known |
| `status` | enum | see "Statuses" |
| `status_reason_code` | string \| null | reason code |
| `status_reason` | string \| null | reason text |
| `status_changed_at` | datetime \| null | last status change: `occurred_at` of the last journal event (before the journal — the write time) |
| `tier` | enum | see "Filter tier" |
| `filter_reason` | string \| null | why it was dropped (`senior`, `experience`, `office`, ...) |
| `stack` | string[] | technologies found in the text: `Python`, `React`, `LLM`, ... |
| `work_format` | string \| null | `remote \| office \| hybrid \| office_or_remote` |
| `english` | string \| null | `A1`..`C2`, `none` |
| `required_years` | int \| null | required experience, years |
| `salary` | string \| null | as written on the platform |
| `search` | string \| null | URL of the bot's search that found the vacancy (`null` for those found before 06.10.2026) |
| `duplicate_of` | string \| null | `id` of the copy where the decision lives (with `status=duplicate`) |
| `cv` | string \| null | the CV the vacancy fits: `backend \| fullstack \| ai` (since 13.11.2026; old ones were back-filled, those dropped by the filter are `null`) |
| `cv_sent` | string \| null | which CV the application went with: `backend \| fullstack \| ai \| universal` (`universal` — the single CV before 09.11.2026); `null` while there is no application |
| `copies` | `[{id, source, status}]` | the same vacancy on other platforms or reposted — the other vacancies of its group, oldest to newest, with status (`null` — a stored copy that no longer exists). Since 17.11.2026 also in the short form, computed by group (before — only copies from the same run) |

Full form (`GET /jobs/{id}`) — everything from the short form, plus:

| Field | Type | Meaning |
|---|---|---|
| `description` | string | full text. Can be short: some platforms (Work.ua) do not serve the vacancy page, then it is the snippet from the list |
| `location` | string \| null | as written on the platform |
| `countries` | string \| null | where candidates are hired from |
| `applicants` | int \| null | how many have applied already (Djinni shows it; `null` on other platforms) |
| `warnings` | string[] | what may not suit the owner, in the filter's opinion: `english` (B2 asked), `abroad` (on DOU "abroad" is not ticked), `ukraine` (must be in Ukraine), `no_description` (the text did not load), `no_python`, `python_plus` (Python only "a plus"), `early_startup` (founding / seed / stealth: such a vacancy is no higher than review) |
| `cv_match` | string[] | skills from the `cv` CV that are in the text: `Python`, `FastAPI`, `PostgreSQL`, ... |
| `cv_gaps` | string[] | what the vacancy requires and the CV lacks: `Celery`, `AWS`, `Kubernetes`, ... |
| `cv_gaps_plus` | string[] | the same, but only "a plus" |
| `requirements` | string \| null | the mandatory-requirements section of `description` as written (under a heading `Requirements / Required skills / What we're looking for / Вимоги / Що ми очікуємо / Требования…`, up to the next section; "Nice to have" is not included); up to 35 lines and 2500 characters. `null` — no such heading, read `description`. Computed on read, since 17.11.2026 |
| `work_hours` | string[] | lines of `description` about hours, timezone or schedule ("Overlap with CET 10:00–14:00"), up to three |
| `history` | `[event]` | **B.** status journal, oldest to newest; `[]` while there are no events |

Journal event (B):

```json
{"id": "5f1c9a02be7d", "occurred_at": "2026-11-02T09:41:00Z", "recorded_at": "2026-11-03T08:15:12Z",
 "from": "replied", "to": "interview", "actor": "ai",
 "reason_code": null, "suggested_code": null, "reason": "Invited to a tech interview on 4.11",
 "evidence": "gmail:18c2f0a1b2", "approximate": false, "undo_of": null, "cause": null}
```

- `occurred_at` — when it **happened** (the email's date; the client passes it, by default the
  moment of writing); `recorded_at` — when the bot wrote it. Analytics go by `occurred_at`.
- `approximate: true` — the event time is a guess: a write without `occurred_at`, an outcome
  button press (pressed later than the email arrived), restored events. Not included in time
  metrics.
- `actor`: `user` (the owner: a button or their request through the client) | `ai` (an AI
  decision) | `system` (the bot: repeats, rejection by silence, initial journal fill). The client
  declares `actor` — it is an audit, not protection.
- `evidence` — how it is known: a Gmail message id or a quote.
- `undo_of` — `id` of the event this one undid; `cause` — the event on another copy that made this
  one a repeat.

## GET /jobs — list

Always sorted newest to oldest: `found_at`, then `id`. Without the vacancy text unless
`with_description=true` is asked (then each has `description`, as in the full form).

| Parameter | Default | Meaning |
|---|---|---|
| `status` | all except `duplicate` | comma-separated statuses |
| `tier` | all except `filtered_out` | comma-separated; `filtered_out` — only explicitly |
| `source` | all | comma-separated platforms |
| `any` / `all` / `none` / `where` | — | keyword search |
| `company` | — | substring of the company name, case-insensitive |
| `url` | — | link to the vacancy (from an email); compared without `www.`, parameters and trailing `/` |
| `source_id` | — | the vacancy's id on the platform itself (as in its link) |
| `search` | — | part of the URL of the search that found the vacancy, case-insensitive |
| `filter_reason` | — | comma-separated filter reasons (`senior,office`); without `tier` searches among all, not only those that came through |
| `reason_code` | — | comma-separated reason codes (`english,experience`) |
| `with_description` | `false` | add the full text of each vacancy |
| `ai_fit` | — | **B.** `yes,maybe,no,none` (`none` = AI has not rated yet) |
| `from` / `to` | last 30 days | by `found_at` |
| `limit` | 50 | 1–200 |
| `cursor` | — | `next_cursor` of the previous page |

Response:

```json
{
  "scope": "own_searches",
  "items": [
    {"id": "6720f1c2a1b2c3d4e5f60718", "title": "Python Developer (AI agents)", "company": "Acme",
     "source": "Djinni", "url": "https://djinni.co/jobs/712345-python-developer-ai-agents/",
     "found_at": "2026-10-28T09:12:44Z", "published_at": "2026-10-28T00:00:00Z",
     "status": "new", "status_reason_code": null, "status_reason": null, "status_changed_at": null,
     "tier": "top", "filter_reason": null, "stack": ["Python", "FastAPI", "LLM"],
     "work_format": "remote", "english": "B1", "required_years": 2, "salary": "$2500–3500",
     "search": "https://djinni.co/jobs/?primary_keyword=Python", "duplicate_of": null,
     "cv": "ai", "cv_sent": null,
     "copies": [{"id": "6720f1c2a1b2c3d4e5f60799", "source": "Dou", "status": "new"}]}
  ],
  "next_cursor": "eyJmIjoiMjAyNi0xMC0yOFQwOToxMjo0NFoiLCJpIjoiNjcyMGYxYzIifQ"
}
```

**One vacancy per group (since 17.11.2026).** A repeat found in a later run, while the group is
still undecided, stays `new` next to the first copy; a decision on either of them decides for both
(the second becomes `duplicate`). So of the group's waiting copies **that match the request's
filters**, the list shows only the latest one (by `found_at`), and the others are in its `copies`
with `status: "new"`. A copy outside the request's period, platform or words does not hide the
other: `?from=<today>` shows today's repeat, `?source=Djinni` — the copy on Djinni. With `url` or
`source_id` you see exactly the copy asked about: the email may be about an application through
it. The funnel and the digest count copies as before.

`next_cursor: null` — no more pages. Keyset pagination (not offset): vacancies found while the
client is paging cause no duplicates or gaps, and land on the first page of the next request.

Typical requests:

- fresh, undecided: `?status=new&from=2026-10-27`
- an email came from a company: `?company=acme&status=applied,replied,interview` or `?url=<link from the email>`
- about AI in the title: `?any=ai,llm,ml,genai,agentic&where=title`
- waiting for manual review (👀 digest): `?tier=review&status=new&from=<2 weeks ago>`
- applications with texts for analysis: `?status=applied,replied,interview,offer,rejected_by_employer&with_description=true`

## GET /jobs/{id} — one vacancy

The full form. `404 not_found` if there is no such vacancy.

## GET /jobs/funnel — funnel

The bot computes it. By default (`by=found`) the cohort is vacancies **found** in `[from, to)`;
`by=event` — journal events in that period, see below. "Applications in October" here means
applications to vacancies found in October. Repeats (`duplicate`) are not in the funnel (one
vacancy — one decision); their number is separate, in `repeats`.

| Parameter | Default | Meaning |
|---|---|---|
| `from` / `to` | last 30 days | by `found_at` (`by=event` — by the events' `occurred_at`) |
| `by` | `found` | `found \| event` |
| `group_by` | `none` | `none \| source \| stack \| week \| tier \| search \| cv` |
| `source`, `any`, `all`, `none`, `where`, `company`, `search` | — | the same filters as the list |

- `group_by=stack`: one vacancy goes into all its technologies, so the sum of the groups is larger
  than the total.
- `group_by=week`: ISO week in `Europe/Berlin` time, key `2026-W44`.
- `group_by=search`: effectiveness of the bot's searches. `key` — the search URL (`(unknown)` for
  vacancies before 06.10.2026), `label` — the same, short ("Djinni · Python"). For the other
  groupings `label` = `key`.
- `group_by=cv`: by the CV the vacancy fits (`cv`), applications too; `(none)` — no CV (dropped by
  the filter). Which CV the group's applications went with is in `applied_with` (`universal` — the
  single CV before 09.11.2026). Before 17.11.2026 an application went into a group by `cv_sent`,
  and `universal` was a group of applications only, at 100%.

Response:

```json
{
  "scope": "own_searches", "by": "found",
  "from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z", "group_by": "none",
  "journal": [], "journal_error": null,
  "groups": [
    {
      "key": "all", "label": "all",
      "found": 412, "repeats": 38, "filtered_out": 301, "surfaced": 111,
      "tiers": {"top": 14, "sent": 52, "review": 45, "filtered_out": 301},
      "decided": 87, "new": 24, "opened": 60, "clicks": 95,
      "reached": {"applied": 31, "replied": 9, "interview": 4, "offer": 0},
      "applied_with": {"universal": 22, "backend": 6, "ai": 3},
      "status": {"new": 24, "applied": 19, "replied": 3, "interview": 2, "offer": 0,
                 "rejected_by_employer": 7, "mismatch": 30, "not_interested": 21, "blocked": 5},
      "rejected_after": {"applied": 4, "replied": 1, "interview": 0, "unknown": 2},
      "reasons": {
        "rejected_by_employer": {"no_response": 3, "experience": 2, "other": 2},
        "mismatch": {"experience": 18, "english": 7, "location": 5},
        "not_interested": {"role": 12, "domain": 6, "conditions": 3},
        "filtered_out": {"senior": 140, "experience": 90, "office": 71}
      },
      "apply_rate": 0.356, "reply_rate": 0.29, "median_hours_to_decision": 3.5
    }
  ]
}
```

- `found` — found, without repeats; `repeats` — repeats, not included in the other numbers.
- `surfaced` — reached Telegram (`tier` not `filtered_out`); `decided` — of them, with a status
  other than `new`.
- `tiers` — how many of the found landed in each `tier`.
- `opened` — how many of the surfaced the owner opened via the link; `clicks` — total click-throughs.
- `reached.X` — reached **stage X or further**. An employer rejection is an answer, so it counts in
  `replied`; except `no_response` — silence is not an answer, such an application stays in
  `applied`.
- `applied_with` — the group's applications by the CV they went with (`cv_sent`); the sum =
  `reached.applied`.
- `rejected_after` — at which stage the rejection came. `unknown` — the rejection was recorded
  before the journal (B).
- `by` — `found`; `journal` — the owner's journal entries for the period (see
  `GET /jobs/journal`), `[]` — there were no changes. The journal storage is unavailable →
  `journal: null` and `journal_error: "unavailable"`: this means "unknown", not "there were no
  changes"; the funnel numbers do not depend on the journal and come as usual.

### `by=event` — what happened in the period (B)

The cohort is `history` events whose `occurred_at` (when it **happened**, not when it was recorded)
is in `[from, to)`. "How many applications did I make in October", "how many interviews were there
this week".

**Undone events are not counted.** An event and its undo (`undo_of`) both drop out, together with
the repeats the event made on other copies (`cause`): a test PATCH or a corrected AI mistake does
not stay in the numbers.

```json
{
  "scope": "own_searches", "by": "event",
  "from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z", "group_by": "none",
  "groups": [
    {
      "key": "all", "label": "all", "events": 42,
      "entered": {"new": 0, "applied": 19, "replied": 6, "interview": 3, "offer": 0,
                  "rejected_by_employer": 8, "mismatch": 4, "not_interested": 2, "blocked": 0},
      "transitions": [{"from": "new", "to": "applied", "count": 19}],
      "applied": 19,
      "reached": {"applied": 19, "replied": 7, "interview": 3, "offer": 0},
      "rejections": {"applied": {"no_response": 4, "no_reason": 2}, "interview": {"experience": 1}},
      "reply_rate": 0.368, "interview_rate": 0.158,
      "time_to_reply": {"count": 5, "median_hours": 52.0, "p75_hours": 96.5}
    }
  ],
  "journal": [{"id": "3", "occurred_at": "2026-10-14T09:00:00Z", "recorded_at": "2026-10-14T09:02:11Z",
               "kind": "cv", "text": "CV: AI projects to the top", "actor": "user"}],
  "journal_error": null
}
```

- `events` — how many events in the period; `entered.X` — how many of them led into status X;
  `transitions` — "from → to" transitions, most frequent first.
- `applied` — applications in the period; `reached.X` — of them, reached stage X or further **as of
  today** (their later events, including after `to`); a `no_response` rejection is not an answer.
  `reply_rate` / `interview_rate` — shares.
- `rejections` — employer rejections in the period: the stage at which the rejection came (the
  event's `from`) → reason code → number. Code `unknown` — a rejection without a code.
- `time_to_reply` — hours from application to the employer's **first** answer (`replied`,
  `interview`, `offer` or a rejection), the period is by the answer time. Not included:
  `approximate` events (on either side) and a `no_response` rejection (silence is not an answer).
  `null` when there are no pairs.
- `group_by` — the same values; `week` — the week of the **event** (for `reached` — the week of
  the application, for `time_to_reply` — the week of the answer).
- This is correlation, not an experiment: with dozens of applications and several approach changes
  in a row, the cause cannot be separated out from `journal`.
- `apply_rate` = `reached.applied / decided` — the share of "applied" among decisions;
  `reply_rate` = `reached.replied / reached.applied`; `median_hours_to_decision` — the median of
  hours from finding to decision. `null` when there is nothing to divide by.

## GET /jobs/digest — weekly digest

The same numbers the bot sends to Telegram on Fridays: the market and the owner's decisions over
`days` days (1–180, 7 by default) with insights. Unlike the funnel, decisions here are counted **by
the moment of decision** (the button press), and the market by vacancies of the owner's field
(without a foreign stack and non-developer roles).

```json
{
  "scope": "own_searches", "period_days": 7,
  "from": "2026-10-22T12:00:00Z", "to": "2026-10-29T12:00:00Z",
  "market": {"in_field": 120, "surfaced": 64, "top_tech": [{"name": "Python", "share": 0.9, "delta": 0.02}], "...": "..."},
  "me": {"decisions": {"applied": 9, "mismatch": 20, "not_interested": 14, "blocked": 3}, "...": "..."},
  "market_insights": [{"kind": "seniority_wall", "count": 40, "share": 0.33}],
  "my_insights": [{"kind": "backlog", "old": 5}],
  "silent_sources": ["Work.ua"]
}
```

- `market` — what is asked for: `in_field` / `in_field_prev` (vacancies of the field, this and
  last week), `surfaced`, `reach_share`, `by_tier`, `years` / `english` / `work_format`
  (distributions), `top_tech` (`share` and `delta` against last week), `salary` (`median`, `low`,
  `high`, `n`), `applicants`, `blockers` (what keeps the owner out: `senior`, `experience`,
  `english`, `office`, ...).
- `me` — decisions: `decisions` / `prev`, `apply_rate` / `apply_rate_prev`, `funnel` (`found`,
  `surfaced`, `opened`, `applied`), `pending`, `by_platform`, `outcomes` (what came of the
  applications, by platform), `by_tier_rate`, `searches` (best and worst searches over 4 weeks),
  `dead_searches`, `mismatch_reasons`, `not_interested_reasons`, `filter_misses`,
  `avg_hours_to_action` (median), `applied_tech`.
- `market_insights` / `my_insights` — up to 5 insights: `{kind, ...numbers}`. `kind`: market —
  `seniority_wall`, `english_gate`, `tech_rising`, `tech_falling`, `volume`, `competition`;
  owner — `platform_gap`, `tiers`, `main_gap`, `filter_miss`, `speed`, `backlog`,
  `dead_search`, `trend`.
- `silent_sources` — platforms the bot searches that gave not a single vacancy in the period
  (broken parsing or a block).
- Shares are from 0 to 1. A number with too little data behind it is `null`.
- The database is unavailable → `503 storage_unavailable` (not zeros).

## Owner's journal (B)

Approach changes — a new CV, a different letter, strategy, the market — with a date, to see them on
the same timeline as the funnel numbers.

`POST /jobs/journal` → `201`:

```json
{"kind": "cv", "text": "CV: AI projects to the top, removed freelance", "occurred_at": "2026-10-14T09:00:00Z"}
```

| Field | Required | Meaning |
|---|---|---|
| `kind` | yes | `cv \| letter \| strategy \| market \| other` |
| `text` | yes | what changed and why, 1–2000 characters |
| `occurred_at` | no | when the change was made; now by default; in the future → `400` |
| `actor` | no | `user` (default) \| `ai` |

The response is the entry: `{id, occurred_at, recorded_at, kind, text, actor}`. An unknown field →
`400`.

`GET /jobs/journal?from=&to=` → `{"items": [entry, ...]}` — the period's entries by `occurred_at`,
oldest to newest; the last 30 days by default. The same entries come in the funnel's `journal`.

## Rejection by silence (B)

Once a day (10:00 `Europe/Berlin`) the bot turns an application into a rejection on its own:
`applied` and no events in `history` for 21 days (`NO_RESPONSE_DAYS`) → `rejected_by_employer`,
`reason_code: no_response`, `actor: system`, a silent message edit without a reply. The rejection's
`occurred_at` is the last event + 21 days (when the silence reached the term), not the day of the
check. The check is switched on by a one-off silence migration of old applications; before it, it
does nothing. Undo it like any change: PATCH or the outcome button. The client may set
`no_response`, but usually has no reason to.

## PATCH /jobs/{id}/status — change the status (B)

```json
{"status": "rejected_by_employer", "expected_status": "applied", "actor": "ai",
 "reason_code": "salary", "reason": "Budget up to $1500, asked for $2500",
 "evidence": "gmail:18c2f0a1b2", "occurred_at": "2026-11-02T09:41:00Z"}
```

| Field | Required | Meaning |
|---|---|---|
| `status` | yes | the new status; `blocked` and `duplicate` → `400` |
| `expected_status` | yes | which status the client saw. Does not match → `409 status_conflict` with `current_status` |
| `actor` | yes | `ai \| user`; `system` → `400` (only the bot sets it) |
| `reason_code` | no | from the vocabulary of the **new** status (`GET /jobs/reasons`); unknown, `muted`, or a code for a status without a vocabulary → `400` |
| `suggested_code` | with `other` | which code would fit, `snake_case`; `other` without it → `400`, it without `other` → `400` |
| `reason` | no | free text, up to 2000 characters |
| `evidence` | with `ai` | a Gmail message id or a quote, up to 1000 characters; `actor: ai` without it → `400` |
| `occurred_at` | no | when it happened; now by default, and then the event is `approximate`. In the future or earlier than `found_at` → `400` |

An unknown field in the body → `400` (a typo must not pass as "no reason").

- Any transition between allowed statuses is valid, including a rollback (`interview` →
  `replied`). A rollback is a new event; the history is not rewritten.
- The same status with the same reason → `200`, `"changed": false`, no event — including when the
  client repeats a request whose response it lost (`expected_status` is then already stale). The
  same status with a **different** reason → a new event. Reason fields missing from the body stay
  as they were for the same status; on a status change they are empty.
- A decision on one copy decides for the group: waiting copies become `duplicate` (events
  `actor: system` with `cause`). A repeat vacancy, or a copy of a group that already has a decision,
  → `409 is_duplicate` with `duplicate_of`: change the status there.
- After writing, the bot edits the vacancy's message in Telegram. A Telegram error does not roll
  back the status.

Response `200`:

```json
{"changed": true, "job": { "...": "full form" }, "telegram": "queued"}
```

`telegram`: `queued` — the edit and/or reply are queued for sending | `skipped` — nothing to show:
there is no message, and the change is not from AI. What Telegram actually did is visible in the
bot's logs; the status is saved either way.

## POST /jobs/status/batch — several statuses at once (B, 16.11.2026)

Up to 25 changes per call. Each is like the body of `PATCH /jobs/{id}/status` plus `job_id`:

```json
{"changes": [
  {"job_id": "6afad4902e80cd0a4f84645b", "status": "not_interested", "expected_status": "new",
   "actor": "ai", "reason_code": "role", "reason": "Embedded, not software", "evidence": "user:vacancy review"},
  {"job_id": "6afad4902e80cd0a4f84645e", "status": "mismatch", "expected_status": "new",
   "actor": "ai", "reason_code": "stack", "evidence": "user:vacancy review"}
]}
```

Changes are independent: a conflict or an error in one does not stop the others. An empty list,
more than 25 changes, or an unknown field → `400` for the whole call; the database is unavailable →
`503`. After a `503` some changes may already have been written: on a retry such a change comes back
as `status_conflict` with `current_status` equal to the wanted status — that means "already done",
not an error.

Response `200`, `results` — in the order of `changes`:

```json
{"results": [
  {"job_id": "6afa…45b", "ok": true, "result": {"changed": true, "job": {"...": "full form"}, "telegram": "queued"}},
  {"job_id": "6afa…45e", "ok": false, "error": {"code": "status_conflict", "message": "…", "current_status": "applied"}}
 ],
 "written": 1, "failed": 1}
```

`error` is the same as a PATCH error body (`invalid_parameter`, `not_found`, `status_conflict` with
`current_status`, `is_duplicate` with `duplicate_of`).

## GET /jobs/reasons — reason codes (B)

```json
{"statuses": {
  "rejected_by_employer": [{"code": "no_reason", "description": "Отказ без причины: шаблонное «выбрали другого кандидата», …"}],
  "mismatch": [{"code": "experience", "description": "Владелец не проходит по опыту или уровню"}],
  "not_interested": [{"code": "role", "description": "Не та роль"}],
  "blocked": [{"code": "site", "description": "Площадка не пустила откликнуться (…). Ставится только кнопкой …"}]
}}
```

`description` comes from the bot as is, in Russian (the product's language).

The codes the client may set (`muted` is a button, it is not here), and since 17.11.2026 the
`blocked` codes, only for reading the history (`blocked/site` in an event): the client does not set
the `blocked` status itself (`400`). The list changes with the bot's releases: a new code appears
here, events before it stay `other` with `suggested_code`.

## Telegram on changes through the API (B)

- **Status — always an edit.** The vacancy's message is edited silently: the status line, buttons
  for the new status, a "🤖" mark for `actor: ai`.
- **Reply to a change from AI.** `replied`, `interview`, `offer` — a separate reply to the
  vacancy's message («🤖 AI: Откликнулся → **Интервью**», the vacancy, the reason), with sound and an
  «↩️ Отменить» (undo) button. The other changes from AI (since 16.11.2026) are collected into one
  silent session message: it is extended by editing while the changes come with a pause under 30
  minutes, up to 12 of them. The «↩️ Отменить…» button under it asks which one to undo; the undone
  one is struck through. Changes from `user` through the API — only a silent edit.
- **No message** (a vacancy from before `message_id` was stored, the 👀 digest, the message was
  deleted): no new vacancy message is sent; a reply from AI comes as a separate message with
  «↩️ Отменить» and a link to the vacancy (loud ones) or goes into the session message, where the
  vacancy is a link.
- **The 👀 digest** — one message a day, extended by editing; a decided vacancy gets its status
  icon in it within a minute.

  The bot does not delete old messages: Telegram only allows deleting messages younger than 48
  hours.
- **«↩️ Отменить»** restores the status and reason that were before the event, and the copies it
  made repeats; the journal gets a new event with `undo_of`. Only the last event can be undone, and
  only while the status is the one it set; otherwise — "already changed", nothing changes.
- **Queue.** Edits and replies go through one sender: one at a time, a pause on `429`
  (`retry_after`), a retry with a growing pause on a timeout and `5xx`. The queue is stored in the
  database and survives a bot restart; the API response does not wait for Telegram.
- Pressing buttons in Telegram works as before and produces no replies. If the status was changed
  while the button was hanging, the bot answers «Статус уже изменён» (status already changed) and
  updates the message.

## Open

Not done yet; will be added without breakage (a new parameter value, a new endpoint).

- **B:** `PUT /jobs/{id}/ai_verdict` — the AI rating `{fit: yes|maybe|no, reason, at}` and the
  `ai_verdict` field in the vacancy; does not change the status. Postponed.
