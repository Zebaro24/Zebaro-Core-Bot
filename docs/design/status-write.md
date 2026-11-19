# Status writes (Jobs API, part B) — analysis

Phase 1 of the spec `B2-partB-status.md` (03.11.2026). For each item: how it is now → recommendation →
cost → what can break (failure mode). No code written.

## 1. Inventory: where the status changes

**Storage** (`container.py:Job`): `user_status` (`pending|applied|mismatch|not_interested|blocked|duplicate`),
`status_reason` (the owner's reason **code**), `status_updated_at`; after applying — `outcome`
(`reply|interview|offer|rejected`) and `outcome_at`; `tg_chat_id/tg_message_id/tg_message_kind`
(since 29.10). No journal: every date is overwritten by the last button press.

**Public status** (`jobs_api.public_status`): `pending→new`, `applied`+`outcome` → `replied|interview|offer|rejected_by_employer`,
the rest as is. No reverse mapping yet.

**Who writes:** only the TG buttons (`handlers/callbacks/job.py`): `job_action_callback` — `find_one`,
then `find_one_and_update` **with no condition on the old status**, plus the group's copies `pending → duplicate`;
`_record_outcome` — the only condition is `user_status: applied`. Readers: `digest.py`, `dedup.py`, `jobs_api.py`.

**Recommendation.** One write function `services/job_searcher/status.py:set_status(job, to, expected, actor, …)`:
validates, does one `find_one_and_update({_id, <expected condition>}, {$set: legacy fields + tg_sync, $push: history})`,
maps the public status back into `user_status`/`outcome`/`status_reason`/dates — so the digest,
dedup and the buttons work without changes. **The TG buttons go through it too** (`actor: user`).
**Cost:** a change to `callbacks/job.py`. **Without it** button events do not reach `history` —
"by event" analytics sees only AI.

## 2. Rejection reasons: name and place

Today there are three different notions: `filter_reason` (the auto-filter: `senior`, `office`), `status_reason` =
the owner's code for `mismatch|not_interested`, in the API — `status_reason_code`; the list filter
`reason_code` searches **by it**, not by the auto-filter (the spec is wrong here). The contract already holds
one field `status_reason_code` with a vocabulary **per status**, including `rejected_by_employer`,
and `status_reason` for text (always `null` now — "comes in part B").

**Recommendation:** introduce no new names. The employer's rejection reason is the same `status_reason_code`
with the `rejected_by_employer` status vocabulary; in an event — `reason_code`, `reason`, `suggested_code`,
`evidence`. `GET /jobs/reasons` → `{status: [{code, description}]}` for all three vocabularies.
The `reason_code` filter and `funnel.reasons.rejected_by_employer` will work on their own.
In storage: `status_reason` stays a code, the text is a new `status_reason_text`.

**Changes to the starting list** (`rejected_by_employer`): take the words from the `mismatch` vocabulary, to
compare "I didn't make the cut myself" with "they rejected me": `experience` (instead of `seniority`), `stack`
(instead of `stack_mismatch`), `location` (instead of `location_permit`), `english` (instead of `language`);
plus `salary`, `position_closed`, `no_response` (the contract had `no_reply` — not released, we change it),
**`no_reason`** — the template "we chose another candidate", the most common email; without it half would go
to `other`. `other` requires `suggested_code`. **Failure mode:** the model sets `other` where
`no_reason` fits → cured by the descriptions in `/jobs/reasons` and a relabelling script.

## 3. Background jobs

There is: APScheduler (`scheduler`, TZ, jobs by `id` in `tg/main.py`), services pause their jobs
in `on_disable`; one-off `asyncio.create_task` (webhooks). No send queue.

**Recommendation:**
- `tg_sync` — an interval job once a minute (`max_instances=1` → one sender = the queue
  from the contract) + after a PATCH a "kick" `job.modify(next_run_time=now)`, so the edit lands in seconds,
  not a minute. State in the document: `tg_sync: {state: pending|done|gone, event_id, notify,
  attempts, next_at}` — survives a restart. The worker renders the message **from the current document**, not from the event.
- S3 — a daily cron (10:00 TZ).
- Neither is tied to pausing `job_searcher`: it depends on Playwright, the API and the sync do not.
- Logic — `services/job_searcher/`, sending — `interfaces/tg/notification/job_status.py`, HTML — `formatters/job.py`.

**Cost / failure mode:** editing "plain" messages today appends the status to `message.html_text`;
the worker has no `Message` object → plain is re-rendered from the document (the text changes slightly).
Two PATCHes in a row: `tg_sync` is overwritten, the reply goes out only about the last event —
acceptable, "Undo" is needed for the last one anyway. The reply is not idempotent: a timeout after an actual
send → a duplicate reply. Rare; accepted.

## 4. Race: a TG button and a PATCH from AI

Today the button writes with no condition → the last write silently wins. Options: (a) leave it;
(b) the button does a CAS on the status read before the write; (c) the button carries the expected status in `callback_data`.
**Recommendation (b):** the window between read and write is closed; on a conflict — «Статус уже изменён»
(status already changed) and the message is redrawn from the DB. (c) is not needed: old buttons do not carry it, and the 64-byte limit is tight.
**What the user sees:** AI set `rejected`, the edit has not arrived yet, they press «Интервью» on the old
buttons → the write goes through (it is their later intent), the message is redrawn, the AI reply's
«↩️ Отменить» answers "already changed" (CAS on `expected_status` = the one AI set). The result always converges
to the DB, because every edit renders the current document.
`↩️ Отменить` = `job:undo:<job_id>:<event_id>` (≈43 bytes): the handler takes `from`/`to` from the event.

**Failure mode:** a decision on a copy turns the waiting copies into `duplicate`; an undo does **not** bring them back.
Proposal: system events get `cause: <event_id>` and are rolled back together with the undo.

## 5. Dates for the backfill

| Field | What it means | Precision |
|---|---|---|
| `found_at` | the bot found it | exact |
| `status_updated_at` | the last status button press (or the switch to `duplicate`) | ≈ time of application / decision, ±hours |
| `outcome_at` | the **last** outcome pressed (since 22.10) | press time, not email time; intermediate ones (`reply` before `interview`) are lost |

**Recommendation:** up to two events per vacancy: `new→<decision>` at `status_updated_at`
and, if there is an `outcome`, `applied→<outcome>` at `outcome_at`; all `actor: system`, `approximate: true`.
No date → `found_at`. Idempotency: write only where `history` is absent
(`{history: {$exists: false}}`). `--dry-run` prints the numbers by status and how many lack dates.

## 6. Corrections to the spec (it disagrees with the code/contract)

1. The contract is at `docs/contracts/jobs-api.md`, not `jobs-api-v1.md`.
2. `reason_code` in `jobs_list` is the **owner's** reasons, not the auto-filter's (item 2).
3. Contract vs spec: "same status, **different reason** → new event" (contract) vs "same status → no event" (spec).
   **Proposal: the contract.** Refining the reason after an email is a valuable event.
4. No message / `message to edit not found`: the contract sends a **new vacancy message** for loud statuses,
   the spec — nothing. **Proposal, the middle:** `tg_sync: gone`, the vacancy is not re-sent, but the notification reply with
   "Undo" is sent as a separate message (`allow_sending_without_reply`) — otherwise an AI change to a vacancy from 👀
   would never reach the owner.
5. Reply: the contract — only `replied|interview|offer`; the spec (D2) — on every AI change, silent except those three.
   Taking the spec; I will fix the contract.
6. `PUT /jobs/{id}/ai_verdict` is in the part B contract, not in the spec. **Proposal:** keep it out of this part, under "Open".
7. The journal (D3) in Mongo contradicts the `CLAUDE.md` rule: new storage is SQLAlchemy + Alembic.
   `history` — in the Mongo document (atomic with the status, otherwise no single update); `journal`
   stands alone → **proposal: SQL** (table `job_journal`, already on the way to P2).
8. `actor` in PATCH: the client sends only `ai|user`; `system` → 400 (only the bot sets it).
9. Button events: «Откликнулся» (applied) — `approximate: false` (pressed right away), outcome buttons —
   `approximate: true` (press time ≠ email time). Otherwise `time_to_reply` is empty until AI arrives.
10. `status_changed_at` is the write time now; proposal: compute it from the last event's `occurred_at`
    (the field's meaning "when it changed" stays, the value becomes more precise).
11. S3: the first run after the backfill would turn every old `applied` into `no_response` at once (their
    approximate dates are >21 days old). The dry-run will show the numbers; proposal: on the first run send one silent summary.
    No replies for `actor: system` — only a silent edit + a line in the weekly digest.
12. `replied` with no preceding `applied` (an email about a vacancy where the application was not marked) — allowed; not in
    `time_to_reply` (no starting point).

## Gaps

- How many vacancies in prod have `outcome` / `status_updated_at` / `tg_message_id` — unknown without the prod DB; the backfill dry-run will show it.
- How MCP reads `reason_code` and `status_reason` — the MCP repo is out of bounds.
- Whether editing a rich message through `bot.edit_message_text(chat_id, message_id, rich_message=…)` works without
  a `Message` object — I will check it as the first step of Phase 2.

## The owner's decisions (03.11.2026)

1. Changing only the reason at the same status → a new event; same status and same reason → no event.
2. No message → a separate reply with «↩️ Отменить» and a link to the vacancy; no new vacancy message is sent.
3. Journal → an SQL table (SQLAlchemy + Alembic). The DB is SQLite `state/zebaro.db` on the server
   (`/srv/zebaro-core/state/`, `DATABASE_URL`), the same one Spotify uses. **There is no backup in the repo** — neither of this
   DB nor of MongoDB (no script, no CD step); whether there is one on the server outside the repo cannot be checked without SSH.
4. `ai_verdict` postponed — under "Open" in the contract.
5. Codes: the `mismatch` vocabulary words + `no_reason` + a separate `work_permit` (≠ `location`).
6. Old `applied` older than 21 days are moved by a **one-off migration in the backfill script** (dry-run → numbers
   to the owner → run): `no_response`, `actor: system`, `approximate: true`, no Telegram.
   The daily S3 is switched on only after it.

Phase 2 — two stops: (1) the rich-message edit, `status.py` + PATCH + `/jobs/reasons` + `history`,
buttons through the shared write + "Undo", the TG sync; (2) the journal, `funnel?by=event`, S3, backfill and relabelling.

**Step 1 (rich by `chat_id`/`message_id`):** works with no workaround — `Message.edit_text` in aiogram 3.31
builds `EditMessageText(chat_id, message_id, rich_message=…)` itself, and `bot.edit_message_text` sends the same request.

**Stop 2 (the owner's additions, 03.11):** `by=event` and `time_to_reply` drop "event + its
undo" pairs (`undo_of`) and the repeats made by the undone event (`cause`). The backfill puts restored events
before the first real one, their last `to` = its `from`; dates on it or later are not trusted (it wrote
them itself) → `found_at`. The daily S3 stays silent until the `meta.jobs_backfill` marker exists. Before running in prod:
`mongodump` + a local copy of `state/zebaro.db` → dry-run with numbers → "ok" → `--apply`.
