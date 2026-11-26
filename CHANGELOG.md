# Zebaro-Core-Bot — changelog

One entry per release, in English, about what changed for the owner as a user of the bot — not a list
of commits. Button labels and bot texts are quoted as they appear (Russian, the bot's language). While
work is going on, changes collect under `## Unreleased`; `scripts/release.py` stamps it with the version
and date and opens a new empty one. The section also becomes the release's GitHub Release and the
forum's release message.

There is one version, in `pyproject.toml`: the bot reads it from there and `release.py` bumps it there.
The `vX.Y.Z` tag is the only thing that deploys to the server.

## Unreleased

## v0.28.1 — 2026-11-26

- **`/github` right after a server reboot lists the repos** instead of "Репо нет" for its first minutes.
  (v0.28.0 never reached the server for this: its check failed in CI. v0.28.1 carries all of it.)

## v0.28.0 — 2026-11-26

- **Everything the bot keeps is in PostgreSQL now** — the vacancies with their whole history, the
  Telegram status sync, the 👀 summaries and AI notes, the VPN traffic, Spotify, GitHub. Moved with every
  value checked against the old store: 2888 vacancies, 906 status events, nothing lost. The vacancy ids
  stay the same, so old buttons and `/jobs/r/…` links keep working, and the Jobs API answers as before.
- **MongoDB is no longer used.** Its container stays for one more release, untouched, in case of a
  rollback. `/mongo` is gone with it.
- **The database being down is handled everywhere**, not only in the Jobs API: Telegram summaries, AI
  notes and the status sync wait and retry instead of failing.

## v0.27.0 — 2026-11-26

- **PostgreSQL is here, empty for now.** A new container, `zebaro-core-pg` (PostgreSQL 17 with pgvector),
  runs next to everything else; its data is in `data/postgres`, part of the one folder to back up. The
  bot still keeps everything where it did — the move of the vacancies, the VPN traffic and the rest
  into it comes with the next release, every value checked on the way.

## v0.26.0 — 2026-11-26

- **The forum's release message carries the whole changelog section**, as a collapsible quote with
  bold, code, links and bullets — no more lines broken in the middle of a sentence. Commit messages
  are tidier too.
- **`/github` pages its repos**, ten to a page; repos you follow come first.
- **The GitHub webhook reads at most 5 MB, even of a chunked body** — an oversized request is cut off
  before it can fill the bot's memory.
- **This changelog is in English now**, the whole history included.

## v0.25.0 — 2026-11-26

- **GitHub rebuilt from scratch.** The bot is now a GitHub App on all your repos: new repos show up at
  once, no webhook per repo and no personal token any more.
- **A quiet log in the forum.** One message per commit and one per release, edited while CI and CD run
  (⏳ → ✅/❌), with no sound and no buttons. Several repos of one system can share one topic.
- **Only what needs you comes to your chat,** with sound and buttons: CI failed on main or a release
  failed («Логи», «Перезапустить»), someone else's issue or PR, a Dependabot alert, a forum topic that
  is gone. Once a failure is fixed, the message turns into «снова зелёный» and disappears an hour later.
- **`/github`** — every repo: its level (all / failures only / off) and its forum topic (pick one, none,
  or create a new one). `/bind` inside a forum topic shows it to the bot.
- **Discord: `/help` finally says something useful** — the list of commands and a link to the bot in
  Telegram, visible only to whoever asked.

## v0.24.1 — 2026-11-25

- **The bot is no longer reachable from the internet directly.** Its port listens on `127.0.0.1` only:
  the way in is the Cloudflare Tunnel (`bot.zebaro.dev`), not the server's IP.
- **A new deploy, shared by every part of Zebaro Core.** A release waits for a green CI, checks that the
  new version is the one that came up, and brings the previous one back by itself on failure. Secrets
  are no longer pasted into the script's text; they live in `.env` on the server (owner only).
- **Data in one folder** — `/srv/zebaro-core/data` (Mongo, `services.json` and SQLite, VPN keys): a backup
  is one folder, and a deploy never touches it. The bot itself works as before.

## v0.24.0 — 2026-11-19

- **Claude's notifications come through the bot.** `POST /notify` (token `NOTIFY_API_TOKEN`): one live
  message per project in the chat — «✅ Zebaro-Core · mcp — готово», a new one replaces the previous.
  It disappears when you answer in Claude (`DELETE /notify?session=…`), on the ✓ button, or after 12
  hours. Contract: `docs/contracts/notify.md`.

## v0.23.0 — 2026-11-17

- **The MCP understands "the site would not let me apply".** `GET /jobs/reasons` also returns the codes
  of the `blocked` status (`site` — «⛔ Сайт не пускает», set only by the button), so Claude knows what
  `blocked/site` in a history means. Setting `blocked` through the API is still not possible.
- **A repeated vacancy no longer confuses Claude.** When the same vacancy came again (a repost or another
  board) before you decided on it, both were `new`, and Claude tripped over "This vacancy is a repeat"
  while sorting them. Now the list shows one vacancy per group, and the other copies are in its `copies`
  (in the list too, with their status and with copies from later runs). A search by the link from an
  email still finds exactly that copy.
- **The gist of a vacancy without "about the company".** The vacancy card in the API (`GET /jobs/{id}`)
  returns `requirements` — the must-have section as written — and `work_hours` — the lines about hours
  and time zone. Claude can screen dozens of vacancies without reading each in full. Computed from the
  stored text, so old vacancies have it too.

## v0.22.1 — 2026-11-17

- **The funnel by CV counts honestly.** `group_by=cv` (MCP: "which CV works better") groups vacancies by
  the CV they fit — applications too. Before, an application went to the group of the CV it was sent
  with: the old universal CV had 100% of applications, and the three new ones had their shares
  understated. Which CV an application went with is in the new field `applied_with`.

## v0.22.0 — 2026-11-16

- **👀 — one message a day.** Partial matches no longer come as a summary after every run: one message a
  day, new ones are added to it by an edit, silently. A vacancy you decided on gets a mark in it
  (✅ / 🚫 / 👎), and the heading says «решено N».
- **Changes by the AI — in one message.** When the AI goes through vacancies in a row, instead of a reply
  to each one there is one message «🤖 AI: N изменений», extended while the changes keep coming less than
  30 minutes apart. «↩️ Отменить…» asks which one to undo. A reply, an interview and an offer still come
  separately and with sound.
- **A batch of statuses in the Jobs API.** `POST /jobs/status/batch` — up to 25 changes per call, with a
  result for each.
- **The filter is stricter to roles that are not about code.** Hardware / Embedded / Network / UAV
  engineers (unless Python is in the title), analysts, Scientists (except AI), administrators,
  coordinators and titles without a word about development are no longer sent — what the AI turned down
  as "wrong role" during the week.
- **👀 are not counted as "waiting for an answer".** In the weekly stats «⏳ Ждут» and the reminder about
  vacancies older than 3 days count only 🔥.

## v0.21.1 — 2026-11-13

- **The Jobs API returns the CV fields.** In v0.21.0 `cv`, `cv_sent`, `cv_match`, `cv_gaps` were computed,
  but the response schema dropped them: the MCP and `/jobs/{id}` did not see them. `group_by=cv` worked
  before too.

## v0.21.0 — 2026-11-13

- **Three CVs — each vacancy gets its own.** The message has a line `📎 CV: Python Backend Engineer` (or
  Fullstack, or AI Engineer) — which CV to apply with. A hint per board: on Djinni «выбери его вместо
  основного» (the main one there is Fullstack), on DOU «приложи PDF».
- **Tiers follow the CV.** 🔥🔥🔥 now means "spot on for this CV", not only "back + front": a Python backend
  is spot on for Backend, Python + React for Fullstack, AI in the title with LLM work for AI. The vacancy
  is checked against the CV's skills, and a line `🧩 Нет в CV: Celery, AWS · плюсом: Kafka` shows what the
  CV lacks. More than one such required technology — no longer 🔥🔥🔥.
- **✉️ A cover letter in one tap.** A button next to «Откликнулся» sends the cover letter for the right CV
  in the vacancy's language (UA or EN) — tapping the block copies it whole. Under it: the salary if they
  ask (the middle of their range or the CV's figure), the PDF's name and «🗑 Убрать».
- **Which CV an application went with.** After «✅ Откликнулся» there are buttons `📎 Backend · Fullstack ·
  AI` at the bottom: the suggested one is marked, tap another if you sent a different one. Old
  applications (before 09.11) are recorded under one shared CV, «AI-Native Fullstack Engineer».
- **Stats by CV** in the weekly «Твои отклики»: how many applications went with each CV and how many got
  an answer (and the one old CV for comparison), how often you apply for each, how many vacancies for
  each came during the week. Once two CVs have 20 applications each, the conclusion says which one to
  improve first. In the Jobs API — the fields `cv`, `cv_sent`, `cv_match`, `cv_gaps` and
  `funnel?group_by=cv`.
- **Data Engineer and the rest that fits no CV — removed.** Data Engineer searches on DOU, Djinni and
  LinkedIn are off; Data Engineer, ML Engineer, Data Scientist, Computer Vision, Research, DevOps / SRE
  and Shopify are filtered out by title. "AI/ML Engineer" and "… (LLM)" stay and go to AI.
- **Dependencies:** fresh vulnerabilities closed in `soupsieve` (2.10 → 4.1, Python 3.11.5 and up) and
  `opentelemetry-api` (1.45.2).

## v0.20.0 — 2026-11-05

- **The home PC is off — the bot says so.** If at 12:00 or later the PC still does not answer, one message
  a day: which boards were skipped (Work.ua, Robota.ua, LinkedIn). Then silence until tomorrow.
- **LinkedIn catches up on what it missed.** It looks not at the last 24 hours but at everything since the
  last successful run — from a day to a week, paging up to 5 pages per search. A PC switched off for the
  weekend no longer loses LinkedIn vacancies.
- **Early startups — no higher than 👀.** Founding / pre-seed / seed / early-stage / stealth / "first
  engineer" in the title or text: the vacancy goes to the summary marked «ранний стартап», not rejected.
  Plain "startup" does not count — outsourcers write that too.
- **An old record no longer hides a live vacancy.** If a vacancy was seen more than 60 days ago and
  nothing was decided on it, its new appearance comes as new (PwC sat as "seen" for a year).
- **HappyMonday is off:** Cloudflare answers 403 even through the home PC, no vacancies since 15.10.
- **Djinni's time is in UTC.** Djinni writes Kyiv time, and the bot stored it as UTC: the publication date
  ran 2–3 hours ahead, sometimes later than the moment the vacancy was found. Old dates are fixed once at
  start.
- **Old data repaired at start:** 363 vacancies from 2025 got a found date (the Jobs API and the MCP did not
  see them), and 72 copies of one vacancy recorded by one run before 23.09 became repeats — the "found"
  and "applied" counters no longer count them twice.

## v0.19.1 — 2026-11-03

- **Backfilling the journal in two steps:** `--apply --skip-silence` restores the history of old vacancies
  and nothing else. "No answer" for old applications and the daily silence check wait for a separate
  run — after the AI has set the real outcomes from the mail.

## v0.19.0 — 2026-11-03

- **A funnel by events** (`/jobs/funnel?by=event`): what happened during a period by the email's date, not
  by when the vacancy was found. How many applications, answers and interviews, at which stage and why
  they turn you down, how many hours until the first answer (median and p75). Undone «↩️ Отменить» does
  not count: neither test changes nor corrected AI mistakes.
- **A journal of your own changes** (`POST/GET /jobs/journal`): a new CV, a different letter, a change of
  strategy — with a date. The funnel shows the entries next to the numbers of the same period.
- **Rejection by silence:** an application with no events for 21 days is marked «Отказ: нет ответа» by the
  bot itself (every day at 10:00, silently). It starts working after the one-off backfill of the journal
  for old vacancies.
- **Backfilling the journal for old vacancies** — a one-off script: events are restored from stored dates
  (marked as approximate), old applications without an answer for 21+ days get "no answer" without
  Telegram messages. Plus relabelling `other` into a new reason code.

## v0.18.0 — 2026-11-03

- **The AI keeps application statuses itself.** A new `PATCH /jobs/{id}/status` in the Jobs API: the model
  sets a status with a reason and evidence (an email id), the bot edits the vacancy's Telegram message and
  replies to it with «🤖 AI: Откликнулся → Отказ (зарплата)» and an «↩️ Отменить» button. With sound —
  only «Ответили», «Интервью», «Оффер». No message — the reply comes separately, with a link to the
  vacancy. Telegram unreachable — the status is saved anyway, the edit arrives later, even after a bot
  restart.
- **A status journal** for every vacancy (`history` in `/jobs/{id}`): who, when (by the email's date, not
  the record's), from which status, why. The Telegram buttons write to the journal too.
- **Employer rejection reasons** — a vocabulary of their own (`GET /jobs/reasons`): no reason, position
  closed, experience, stack, location, work permit, English, salary, silence. Nothing fits — `other` with
  a suggested code.
- **A button no longer overwrites someone else's change:** if the AI changed the status while the button
  was waiting, the bot says «Статус уже изменён» and refreshes the message. Pressing «✅ Откликнулся» again
  on an old message does not reset «Интервью».

## v0.17.0 — 2026-10-29

- **One Jobs API for the MCP** at `/jobs/*` (contract: `docs/contracts/jobs-api.md`), read-only for now: a
  vacancy list filtered by status, board, company, the link from an email, search and whole words
  (`any=ai` finds "AI/ML" but not "email"; Cyrillic too), paging without duplicates, one vacancy with its
  full text, a funnel "found → applied → answered → interview → offer" with rejection reasons — by board,
  stack, search and week, and the Friday digest's numbers. Token: `JOBS_API_TOKEN`.
- **The old analytics removed:** `/jobs/stats/weekly`, `/jobs/stats/digest`, `/jobs/stats/searches`,
  `/jobs/review`, `/jobs/search`, `/jobs/job/<id>`, the script `scripts/job_stats.py` and the token
  `JOB_STATS_API_TOKEN` — their data is in the new API now. What the script's `fields` command showed is in
  the `/jobs/{id}` card (`applicants` and `warnings` added). The `replay` command (running a new filter
  over old answers) was not carried over — how to bring it back is in the notes. `/jobs/r/<id>` (the
  vacancy buttons) works as before; so do `/job_stats` and the Friday digest in Telegram.
- **The bot remembers each vacancy's Telegram message** — so that later, when the AI changes the status,
  it edits exactly that message.

## v0.16.0 — 2026-10-28

- **More vacancies.** Djinni searches "python" in the whole vacancy text, not only in the Python category:
  the category gave about 10 vacancies a month, the text search about 7 a day (Django, fullstack, AI and
  data positions from other categories). Two pages are read.
- **A new source — LinkedIn**: remote vacancies of Ukrainian companies from the last day for python, data
  engineer and AI engineer. No login, through the home PC.
- **Data Engineer** — new searches on DOU and Djinni. Such vacancies without Python in the title come as 👀.
- **Searches reworked by measurement.** Djinni: the search "AI, LLM, agent" looked for all three words at
  once and found one vacancy — now LLM, "AI engineer" and "AI agents" separately; Django added, FastAPI
  and Next.js stay; React removed. DOU Front End removed — no frontend needed. Robota.ua and Work.ua search
  just "python" (Robota.ua — 56 vacancies instead of a handful), Work.ua also "AI engineer"; Robota.ua
  full-stack removed (0 applications out of 23 in a month).
- **A search every hour from 9:00 to 21:00** (was 10, 12, 14, 16): a vacancy arrives within an hour of
  being published, while it still has few applicants.

## v0.15.0 — 2026-10-23

- **Vacancies without Python no longer come.** Frontend, JS/TS fullstack and a Node backend without Python
  are filtered out (frontend by title — before the page is even opened). AI roles without Python in the
  text still come as 👀 marked «Python в тексте не упомянут». If Python is only a "nice to have", the
  vacancy drops to 👀 with a warning.
- **🔥🔥🔥 for a Python backend too.** Python in the title, the level fits, no warnings — now it is "spot on"
  even without frontend; without a level — 🔥 instead of 👀.
- **The stack highlighted right in the description:** the main stack with a marker, the bonus stack in
  bold, underlined — a foreign stack (Node, Java, PHP…), 4+ years, senior, English above B1, office.
- **What happened with the company before is visible.** 📌 lines: where in this company you applied, what
  you declined, what you opened in the last six months, and «похоже, это она же» for a renamed vacancy. A
  repeat of a vacancy you answered is caught within 120 days (was 30); a repeat shows «👁 ссылку уже
  открывал».
- **🔕 Don't send this company** — a new reason in «Не интересно»: this company's vacancies will not come
  again.
- **👀 in one summary.** Partial matches come in one message after a run: title, company, stack, warnings;
  a numbered button opens the vacancy in full.
- **What happened after applying.** An applied vacancy keeps the buttons «📨 Ответили / 🗓 Интервью / 🎉
  Оффер / ❌ Отказ»; the digest shows how many applications got an answer and an interview, and on which
  boards.
- The filter no longer cuts "Junior–Senior" as senior, "(Security domain)" as not development, and "Right
  Hand to the CTO" as lead.
- **Spotify:** while the history is loading, the bot sends neither «чьи это деньги?» nor charge
  notifications; an old «новый участник» button for an already sorted sender no longer creates a second
  member.

## v0.14.1 — 2026-10-15

- **Spotify sets itself up.** On the first start the bot takes the jar and the card from the settings, loads
  the whole history since 12.08.2022, creates members from the jar's senders and sends a summary — all
  that is left by hand is sending out the invitations.

## v0.14.0 — 2026-10-15

- **Spotify Family in the bot: `/spotify`.** The Monobank jar and the Spotify charges on the black card are
  pulled in by themselves (a webhook at once, a statement poll once a day and on the «Обновить» button),
  the whole history since the first charge.
  Each charge is split equally between those who were in the plan that day; you can see who paid in how
  much, who owes, and "paid until" which month.
  - An unknown sender is asked about once: whose second account it is, a new member, or «не учитывать».
  - Three days and one day before a charge, members who are short get a reminder with the jar's button and
    the amount; you get how much is in the jar and on the card and what to do («сними X из банки» or «не
    хватает X»). After a charge — debtors at once and three days later; you get a summary and a warning if
    Spotify changed its dollar price.
  - Manual corrections (money outside the jar, a written-off debt) with a comment, marked 📝. A member
    leaves and joins by date — best right after a charge; on leaving the bot writes the final balance.
  - Members connect through an invitation link and see their own `/spotify`; those not connected are marked
    ⚠️, and the invitation and the reminder can be sent again with a button.
- **The first SQL database.** Spotify is stored in SQLite (`state/zebaro.db`) through SQLAlchemy and Alembic
  migrations, which the bot applies itself at start — groundwork for moving to Postgres.

## v0.13.3 — 2026-10-06

- **Robota.ua: links and descriptions work again.** `www.robota.ua` started answering 404 for every
  vacancy — the «Вакансия» button led nowhere and the description did not load. Links are now without
  `www`; stored ones are fixed at start, so the buttons in old messages open too.

- **Work.ua: the company is a company again.** Every vacancy with a salary had «Після всіх відрахувань» —
  the caption under the salary — instead of the company. Now the card's lines are read by their icons:
  company, salary (`💰 30 000 – 70 000 грн`), format and experience. Stored vacancies with that caption
  instead of a company are cleaned at start.

## v0.13.2 — 2026-10-06

- **Ships the Playwright fix from v0.13.1:** that release stopped at the pre-deploy check (the new version
  test needed environment variables that CI does not have) and never reached the server. The version now
  lives only in `pyproject.toml`.

## v0.13.1 — 2026-10-06

- **The vacancy search works again:** Playwright 1.63 listened only inside its own container by default,
  and after v0.13.0 the bot wrote "Playwright unavailable" on every search. The browser server is open to
  the bot again, as before.

## v0.13.0 — 2026-10-06

- **Three vacancy tiers:** 🔥🔥🔥 — spot on: Python and React/Next.js, your level and experience, nothing to
  double-check in the conditions; comes with sound and the "fire" effect. 🔥 — your stack, 👀 — partial,
  silent. On the old database you applied to 64% of the vacancies that would now be 🔥🔥🔥 (31% on
  average).

- **Conditions right in the message:** a line `📍 Удалённо · Весь світ · 🗣 B2 · 💰 до $2500 · 👥 227
  откликов` and ⚠️ with what to check before applying: B2 against your B1, «віддалено» without «за
  кордоном» on DOU, a phrase about being in Ukraine, a description that did not load. From Djinni all of
  it comes from the card — exactly the fields Djinni uses to let an application through or not.

- **The filter is stricter where you said no anyway:** from 4 years of experience (by the main
  requirement, not the minimum: "5+ commercial, 3+ Go" is 5), English above B2, office and hybrid,
  countries outside Europe and worldwide, «шукаємо Senior» in the description with no mention of
  middle/junior, trainee and internships, instructors for children, data analyst, support without
  development, military units. On the old database it would have filtered out 115 of your 264 "not
  interested" by itself.

- **The filter does not lose what you need:** a vacancy whose description did not load comes as 👀 with a
  note instead of being dropped as "stack did not match"; an AI vacancy with no stack in its text comes
  too; the word marketing in a title ("Developer in Marketing team") no longer makes it "not
  development".

- **New buttons:** ✅ Откликнулся · 🚫 Не прохожу · 👎 Не интересно. After a "no" you can pick a reason in
  the same message (experience, office/country, English, stack, the site won't let me — or role, stack,
  domain, conditions). «Сайт не пускает» works like the former ⛔ Djinni: a copy from another board is
  sent.

- **Searches:** Djinni searches only remote with up to 3 years of experience right away, a Python + LLM
  search added; Robota.ua and Work.ua also search full-stack. BazaIT (all vacancies from 2025) and
  Wellfound (non-Ukrainian companies, 7 applications out of 40 decisions) are off. Every vacancy
  remembers which search found it.

- **Fixed:** Robota.ua and HappyMonday dates are real dates, not «2 дні тому»; the company on HappyMonday
  and Work.ua (was empty or «·»); the «НОВОЕ» badge in No Fluff Jobs titles; Robota.ua descriptions no
  longer eat the limit DOU used up (the limit is per board now).

- **Weekly analytics — two parts with conclusions:** «🌍 Кого ищут компании» — key numbers with the trend
  against last week, experience and English scales marked «← ты», what is asked for more often (with ↑↓),
  salaries, competition, what cuts you off. «👤 Твои отклики» — the funnel "found → sent → opened →
  applied", answers with a trend, boards, tiers, what is missing, the best and worst searches. Each part
  has «💡 Выводы»: the bot says what matters itself («стена — уровень: 54% вакансий», «B2 открыл бы ещё 19
  вакансий», «на DOU 64% откликов, на Djinni 9%»).

- **Dates are the same everywhere:** old Robota.ua dates like «2 дні тому» are recalculated at start into
  real ones from the moment the vacancy was found.

- **Analytics from the computer:** `job_stats.py searches` (each search: found, sent, applications),
  `digest`, `audit` (your "no"s by reason), `fields` (what the parsers extracted), and `poetry run python
  scripts/job_stats.py replay` — the filter from the working copy against your answers across the whole
  database. In the API: `/jobs/stats/digest`, `/jobs/stats/searches`, and in `/jobs/search` —
  `status_reason`, `search_url` and `skip`.

- **The command menu:** the bot sets the list of commands itself at start — its own for everyone, for
  server access and for the admin. No need to press /start to see them any more.

- **Libraries updated:** vulnerabilities in pymongo and multidict closed; FastAPI, uvicorn and Playwright
  are fresh — the browser in the container is 1.63 too. Code checks are now done by ruff instead of black,
  isort, flake8 and bandit.

- **/server_speed measures again:** speedtest.net through the old library returned a ping of 1 800 000 ms
  and 0 Mbps. Now the measurement goes through Cloudflare: ping with jitter, download and upload with
  scales, live progress in the message; an error is shown instead of hanging the message.

## v0.12.0 — 2026-09-30

- **Vacancy analytics from the computer:** `python scripts/job_stats.py` shows the weekly stats, a vacancy
  search (`search`), any vacancy in full by id (`job`) and applications with their descriptions (`applied
  --out applied.md`) — the file can go straight to an AI for review. Read-only, under the same token
  `JOB_STATS_API_TOKEN`.

## v0.11.1 — 2026-09-25

- **The VPN keeps in touch with devices behind a home router:** every profile now sends a keepalive every 25
  seconds. Without it the server could not reach the laptop itself after a minute of silence — and the
  Work.ua search through the laptop worked on and off. Applies to files issued after the update; in an
  already installed profile the line `PersistentKeepalive = 25` can be added by hand.

- **A tunnel name without a double "Zebaro":** the device `Zebaro-Laptop` gets the files `Zebaro-Laptop.conf`,
  not `Zebaro-Zebaro-Laptop.conf`. Files already issued work as before.

## v0.11.0 — 2026-09-24

- **Work.ua, Robota.ua and HappyMonday — through your laptop.** These three boards refuse the server's IP but
  let the home one in. Now the bot opens them through a proxy on the laptop (`10.0.0.2` in the VPN). If the
  laptop is off or asleep, these boards are skipped within 2 seconds and the others are searched as usual;
  the log says "the home PC is not reachable".

## v0.10.2 — 2026-09-24

- **The VPN rules on the server no longer multiply** on WireGuard restarts: each rule is first removed in
  all its copies and then set once.

## v0.10.1 — 2026-09-24

- **There is internet through the VPN again.** wg-easy wrote its NAT rules into the old iptables tables,
  while the server and Docker live in nftables — the full profile connected, but traffic went no further
  than the server. The bot now sets the right rules for wg-easy itself (nftables) and watches them at every
  start; it also closes the wg-easy panel to people in the VPN. Checked with a live connection: the
  internet goes through the server, ads are cut by AdGuard.

## v0.10.0 — 2026-09-24

- **Your own WireGuard VPN — `/vpn`.** Instead of OpenVPN — WireGuard (wg-easy) on the same server, managed
  from the bot in the style of `/server_status`:
  - a table of people: 🟢 online / ⚪ offline / ⏸️ disabled / ⌛ expired, address, traffic ↓↑ for the week,
    last seen; buttons two to a row;
  - «➕ Добавить»: a name and, if you like, an address number — `Олена 18` → `10.0.0.18`. Addresses are easy
    to remember: `10.0.0.1` — the server, `.2–.9` — your devices, `.10–.99` — a person's own number,
    `.100+` — automatic. The number can be changed later — the bot sends the new files at once;
  - a person's card: IP, where they connect from, traffic for today / the week / all time, enable/disable,
    access period (+1 / +7 / +30 days, unlimited), name, IP, delete;
  - **files to choose from, in two separate messages:** «📄 Конфиги» — two named profiles
    (`Zebaro-Olena.conf` — the whole internet through the VPN, `Zebaro-Olena-LAN.conf` — only the VPN
    network) or «💾 EXE для Windows» — `Zebaro-VPN-Olena.exe`: installs WireGuard itself (if it is missing or
    old; a newer one is left alone), adds both profiles and turns the VPN on if the person has no other one
    on right now. Other tunnels are not touched;
  - DNS — AdGuard: ads are cut for everyone in the VPN;
  - notifications: a person connected for the first time; access ends tomorrow (with «+7» / «+30 дней»
    buttons); on Fridays — a table of who used how much traffic.

- **`/server_status` — in tables and compact.** Instead of a six-line block for each project — one table:
  status, how many containers run, RAM, CPU, uptime; the total RAM and CPU on top, the open ports at the
  bottom (UDP is labelled now: `51820/udp`). Buttons — two to a row with a status (🟢/🟡/🔴), running and
  heavy ones on top, pages with arrows if there are more than 10 projects. A project — a table of
  containers with ports; a container — a table (status, image, RAM, CPU, uptime, restarts, ports) and a
  collapsed log. «Вернуться» from a container leads to its project; after start/stop/restart the card
  refreshes at once.
- **CPU in `/server_status` was shown 100 times higher than it is** — fixed.

- **One vacancy — one message and one decision.** The same vacancy (the same title and company within 30
  days) on DOU and Djinni, or re-posted on Djinni under a new number, no longer comes several times:
  - one copy comes per run — from the most convenient board (DOU first, Djinni last), the other copies as
    `🔗 Djinni` buttons under it;
  - «Откликнулся» or «Не интересует» on any copy closes the whole vacancy: a repeat will not come, and in
    the stats it is one decision, not two;
  - a repeat you have not answered yet comes with «🔁 Уже присылал 21.09 с Djinni»;
  - Djinni vacancies get a new button **«⛔ Djinni не пускает»** — for when it will not let you apply
    because of experience: it is not a rejection, and the same vacancy from DOU or Work.ua comes marked
    «на Djinni не пустило». In the digest — a line of its own.

## v0.9.0 — 2026-09-23

- **The zebaro.dev contact form arrives in Telegram.** A message from the site comes through the same bot:
  name, how to reply, the text in a collapsed block and the site's language flag; for an @username or a
  link — a «💬 Ответить» button. Accepted only from the site's container with a shared token, the endpoint
  is invisible from outside; no more than 5 messages an hour from one sender and 30 in total. Message texts
  are not logged. Starts working once the `SITE_CONTACT_TOKEN` secret is in GitHub.

## v0.8.0 — 2026-09-23

- **The filter learned from your decisions** (218 «Откликнулся» / «Не интересует» presses in a week). Now
  vacancies you never applied to no longer come:
  - another main stack in the title — Java, Kotlin, C#/.NET, PHP/Laravel, Angular, Vue, React Native,
    Flutter, mobile, Ruby, Golang, WordPress (even "React and C#"); Node.js stays — you do apply to
    "Node + React";
  - managers, analysts, consultants, content, security and "Team Leader";
  - office instead of remote on Wellfound ("In office • London", "Dublin") and vacancies for Latin America,
    South Africa, the USA and Canada.

  On your past decisions this removes another third of the rejections and touches no application.

- **Work.ua, Robota.ua and HappyMonday find vacancies again.** All three answered the server with
  Cloudflare's «Трохи зачекайте…» stub on every run. The bot now opens the pages with a full Chromium
  instead of the cut-down headless build — the check passes. Robota.ua and HappyMonday have the full
  description; Work.ua's vacancy pages are guarded more strictly, so its vacancies come with the short
  description from the list — the full one behind the «Вакансия» button.

- **New searches, each checked live:** on Djinni — Python, FastAPI and Next.js (FastAPI at once found
  "FastAPI + React" and "Python + Next.js", which no search had), Front End with relocation on DOU,
  fullstack on No Fluff Jobs and React vacancies across Europe on Wellfound.

- **One broken card no longer ruins the whole search.** If Djinni returned a page before drawing the dates,
  the parser crashed — and nothing came from any board in that run. Now such a card is taken without a
  date, and a completely unclear one is skipped with a log entry; a page that did not open does not get
  in the others' way either.

- **You can see why a vacancy came** — two or three short lines under the header: which half of the stack
  matched («🔥 Бэк + фронт — Python, FastAPI · React», «👀 Бэкенд — Python»), what else counts as a plus
  (➕), and how many years of experience they ask and which level is in the title (🎓 от 3 лет · Middle).
  The cryptic «оценка N» at the bottom is gone.

- **Juniors are welcome again.** Junior in the title is no longer cut: a strong junior with a couple of years
  of experience is your level. Only internships are cut (trainee, intern, стажування), and only if there is
  no junior or middle next to it in the title. The rule "they ask 5+ years — so it is a senior" stays.

- **A vacancy search at 10:00 too:** the schedule is 10, 12, 14 and 16. The morning run catches what was
  posted overnight, before a queue of applicants builds up.

- **A vacancy no longer comes twice.** DOU shows it in several searches at once (Python and Fullstack,
  remote and relocation) and also in the "hot" block — now it comes once per run.

## v0.7.0 — 2026-09-17

- **`/job_stats` — stats on request**, optionally with a period: `/job_stats 30`. The same digest that
  comes on Fridays, but now with a 👀 column, a list of "what you apply to" against "what you decline" and
  a warning about boards that gave nothing. The command is added to the `/start` menu.
- **The vacancy message is neatly laid out:** section titles as real headings, lists as lists (including
  those written on the site with `-` and `1.`), the matched stack highlighted, a divider between the
  header and the description, the preview as a quote.
- **The vacancy's location** — in the message header, next to the company and the board.
- **The filter is stricter to what does not fit:** vacancies from another continent (India etc.), ones
  hanging on the site for more than two months, and those asking 5+ years of experience no longer come —
  even if the title says "Middle".
- **Wellfound no longer pours Indian vacancies:** the search goes through European pages, not worldwide
  remote.
- **New searches on DOU** — Front End, Fullstack (remote and relocation) and **React on Djinni**: before,
  no search looked for frontend vacancies, although React and Next.js are half of 🔥.
- **Removed from BazaIT:** Node.js and Full Stack Data Analyst positions — not your stack.
- **Clearer when a board is silent:** an empty result is logged with the page's title, and the bot now
  waits out the "are you a robot" check (Work.ua) and retries.

## v0.6.0 — 2026-09-17

- **Vacancies come as nice messages** (Telegram's new format): title, company, board, date, a "what matched"
  line and the description in paragraphs and lists, as on the site. Under the title — a short preview, the
  full description in a collapsed «📄 Описание полностью» block. No more «проверь сам».
- **The full description, not two lines from the list.** The bot opens the page of every vacancy that
  passed the title filter and takes the text from there (DOU, Work.ua, Robota.ua, No Fluff Jobs,
  HappyMonday, BazaIT, Wellfound; Djinni had the full text right in the list).
- **A filter by your stack.** 🔥 — both backend (Python / FastAPI) and frontend (React / Next.js); 👀 —
  something matched; the more matched, the higher in the batch. Senior, lead, head, architect and junior
  are always skipped, except "Middle/Senior" and "Junior/Middle".
- 🔥 come with sound, 👀 silently.
- **Coloured buttons:** the link blue, «Откликнулся» green, «Не интересует» red; the status sits right
  under the company.
- **The «Вакансия» link no longer gives 404** — in new and in already sent messages.
- **The bot no longer freezes during a search** and does not lose vacancies to Telegram's flood control; a
  second `/get_job_openings` while the first is running answers «уже ищу».
- **Robota.ua and No Fluff Jobs find vacancies again:** the bot waits until the cards are drawn.
- **The Friday digest — in tables**, and it shows why vacancies were not sent.

## v0.5.1 — 2026-09-17

- **The vacancy search works again.** The Playwright server was a version behind the client, and the
  browser did not connect at all. A test now fails if the versions drift apart again.
- **A failed command no longer repeats in a loop.** The bot answered Telegram with an error, and Telegram
  sent `/get_job_openings` again every minute and a half.
- **The schedule in local time.** Searches at 12, 14 and 16 are now 12, 14 and 16 Berlin time, not two
  hours later; the logs are in local time too.
- **`/services` remembers its switches.** Before, everything was on again after every restart: the state
  file on the server turned out to be a folder.
- Container logs as a file — the last 5000 lines instead of 20.

## v0.5.0 — 2026-09-17

- **Vacancies are scored, not just filtered.** Each one gets points for stack and role: 🔥 — sent at once,
  ❓ — doubtful, the rest quietly goes to the database.
- **«Откликнулся» and «Не интересует» buttons** — the status is saved, the message is updated in place.
- **New boards:** HappyMonday, BazaIT, Wellfound; Djinni finds vacancies again.
- **Duplicates from different sites are marked** — «похоже, уже видел на DOU».
- **The Friday digest** — how many were found, how many sent, what you applied to.
