# Jobs API — контракт

Бот Zebaro-Core-Bot — backend поиска работы. Этот документ — **единственный источник** для
клиента (MCP `zebaro-core-mcp`, tools `jobs_*`): по нему работают с вакансиями, не читая код
бота. Схемы ответов дублирует `/openapi.json` бота; при расхождении прав этот файл.

- Часть **A** — чтение: `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/funnel`, `GET /jobs/digest`.
- Часть **B** — запись и аналитика по событиям: `PATCH /jobs/{id}/status`, `GET /jobs/reasons`,
  поле `history` в `GET /jobs/{id}`, правка сообщений в Telegram, журнал владельца
  (`POST/GET /jobs/journal`), `GET /jobs/funnel?by=event`, отказ по тишине. Ещё не вышло
  (см. «Открыто»): `PUT /jobs/{id}/ai_verdict`.
- `/jobs/r/{id}` — не часть API, хоть и есть в `/openapi.json`: публичная ссылка за кнопкой
  вакансии в Telegram (считает клики и перенаправляет на площадку), без токена.

## Общие правила

**Адрес и доступ.** `https://<host>/jobs...`, заголовок `Authorization: Bearer <JOBS_API_TOKEN>`.
Без токена или с чужим → `401` (раньше любой проверки параметров).

**Совместимость.** Правило одно: изменения **только добавляют** — новые поля, новые значения
enum, новые параметры, новые эндпоинты. Ничего не удаляется и не переименовывается. Клиент —
tolerant reader: неизвестные поля пропускает, неизвестное значение enum показывает как есть.

**Даты.** ISO 8601 в UTC с `Z`: `2026-10-29T14:03:00Z`. Параметры `from` / `to` принимают дату
(`2026-10-01` = `2026-10-01T00:00:00Z`) или дату-время; `from` включительно, `to` — нет.
Пример «за октябрь»: `from=2026-10-01&to=2026-11-01`.

**Идентификатор.** `id` — непрозрачная строка. Не разбирать, не сравнивать на «больше-меньше».
Тот же `id` стоит в кнопках вакансии в Telegram.

**Охват (`scope`).** Списки и агрегаты несут поле `"scope": "own_searches"`: данные — это
вакансии, **найденные поисками бота** (его набор площадок и запросов), а не рынок. «Вакансий
про AI стало больше» может значить «поиски стали шире». Выводы о рынке из этих данных не делать.

**Ошибки.** Всегда так:

```json
{"error": {"code": "invalid_parameter", "message": "limit: 500 is more than 200"}}
```

`message` пишется для читателя-LLM: какой параметр и почему.

| HTTP | `code` | Когда |
|---|---|---|
| 400 | `invalid_parameter` | неизвестный параметр-значение, `from >= to`, `limit` вне 1–200, неизвестный статус, кривой `cursor`; в PATCH — запрещённый статус, неизвестное поле или код, нет `evidence` у `actor: ai` |
| 401 | `unauthorized` | нет токена или неверный |
| 404 | `not_found` | нет вакансии с таким `id` |
| 409 | `status_conflict` | `expected_status` не совпал с текущим (B); в `error` есть `current_status` |
| 409 | `is_duplicate` | статус ставят повтору, решение живёт на другой копии (B); в `error` есть `duplicate_of` |
| 503 | `storage_unavailable` | база недоступна; повторить позже |

Пустой период или фильтр, под который ничего не попало, — это `200` с пустым списком или
нулями, а не ошибка.

## Статусы

Один публичный `status` — где вакансия на пути «нашли → откликнулся → чем кончилось».

| `status` | Смысл | Ставит |
|---|---|---|
| `new` | ещё не решено | бот при нахождении |
| `applied` | откликнулся, ответа пока нет | владелец, AI |
| `replied` | работодатель ответил | владелец, AI |
| `interview` | назначено или прошло интервью | владелец, AI |
| `offer` | оффер | владелец, AI |
| `rejected_by_employer` | отказ работодателя (на любом этапе после отклика) | владелец, AI |
| `mismatch` | владелец не проходит по требованиям | владелец, AI |
| `not_interested` | владельцу не интересно | владелец, AI |
| `blocked` | площадка не пускает откликнуться (Djinni); копия с другой площадки придёт сама | **только кнопка в Telegram** |
| `duplicate` | повтор вакансии, решение по которой живёт на другой копии (`duplicate_of`) | только бот |

**Причина** — два поля, оба необязательные:

- `status_reason_code` — код из словаря статуса (`GET /jobs/reasons` отдаёт их с описаниями):
  - `mismatch`: `experience | location | english | stack | other`;
  - `not_interested`: `role | stack | domain | conditions | other | muted` (`muted` =
    «компанию больше не присылать», ставится **только кнопкой**);
  - `rejected_by_employer`: `no_response | no_reason | position_closed | experience | stack |
    location | work_permit | english | salary | other`. Слова те же, что у `mismatch`, где смысл тот же:
    «сам не прохожу по опыту» и «отказали по опыту» сравнимы. `no_reason` — шаблонный отказ
    («выбрали другого кандидата»), `no_response` — тишина после отклика, `work_permit` — нет
    разрешения на работу (≠ `location`).
  - Не подошёл ни один → `other` + `suggested_code` (какой код бы подошёл, `snake_case`) + `reason`.
- `status_reason` — свободный текст (например, выжимка из письма с отказом). Хранится всегда,
  даже при подходящем коде.

Это причины **решения** (владельца или работодателя). Почему вакансию отбросил фильтр бота —
другое поле, `filter_reason`; фильтры списка: `reason_code` — по `status_reason_code`,
`filter_reason` — по `filter_reason`.

**Отбор фильтром (`tier`)** — отдельная ось, не статус: как бот оценил вакансию при нахождении.

| `tier` | Смысл |
|---|---|
| `top` | точно в стек владельца, пришла в Telegram со звуком |
| `sent` | подходит, пришла в Telegram |
| `review` | частичное совпадение, пришла в общей сводке 👀 |
| `filtered_out` | фильтр отбросил, в Telegram не приходила; почему — `filter_reason` |

## Поиск по словам (список и воронка)

| Параметр | Смысл |
|---|---|
| `any=ai,llm,rag` | есть **хотя бы одно** из слов |
| `all=python,react` | есть **все** слова |
| `none=senior,php` | нет **ни одного** из слов |
| `where=title\|description\|both` | где искать, по умолчанию `both` |

- Слова через запятую; фраза с пробелом — одно слово (`any=machine learning`). До 20 слов на
  параметр, каждое от 1 до 50 символов.
- Совпадение — **целое слово без учёта регистра**: соседний символ не буква и не цифра.
  `any=ai` находит «AI Engineer», «AI/ML», «AI-powered», но **не** «email» и не «training».
  Кириллица так же: `any=джун` находит «Джун», но не «Джуніор».
- Символы внутри слова буквальные: `any=c#,next.js,node.js` работают как написано.
- Параметры складываются через «И»: `any=ai,llm&none=senior&where=title`.

## Вакансия

Краткая форма (элемент списка):

| Поле | Тип | Смысл |
|---|---|---|
| `id` | string | идентификатор |
| `title` | string | название |
| `company` | string \| null | компания; бывает `null`, когда площадка её не показала |
| `source` | string | площадка: `Djinni`, `Dou`, `Work.ua`, `Robota.ua`, `LinkedIn`, ... |
| `url` | string | ссылка на вакансию на площадке |
| `found_at` | datetime | когда бот её нашёл |
| `published_at` | datetime \| null | дата публикации на площадке, если она известна |
| `status` | enum | см. «Статусы» |
| `status_reason_code` | string \| null | код причины |
| `status_reason` | string \| null | текст причины |
| `status_changed_at` | datetime \| null | последнее изменение статуса: `occurred_at` последнего события журнала (до журнала — время записи) |
| `tier` | enum | см. «Отбор фильтром» |
| `filter_reason` | string \| null | почему отброшена (`senior`, `experience`, `office`, ...) |
| `stack` | string[] | технологии, найденные в тексте: `Python`, `React`, `LLM`, ... |
| `work_format` | string \| null | `remote \| office \| hybrid \| office_or_remote` |
| `english` | string \| null | `A1`..`C2`, `none` |
| `required_years` | int \| null | требуемый опыт, лет |
| `salary` | string \| null | как написано на площадке |
| `search` | string \| null | URL поиска бота, который нашёл вакансию (`null` у найденных до 06.10.2026) |
| `duplicate_of` | string \| null | `id` копии, где живёт решение (у `status=duplicate`) |

Полная форма (`GET /jobs/{id}`) — всё из краткой и ещё:

| Поле | Тип | Смысл |
|---|---|---|
| `description` | string | полный текст. Бывает коротким: часть площадок (Work.ua) не отдаёт страницу вакансии, тогда это фрагмент из списка |
| `location` | string \| null | как написано на площадке |
| `countries` | string \| null | откуда берут кандидатов |
| `applicants` | int \| null | сколько уже откликнулось (показывает Djinni; у других площадок `null`) |
| `warnings` | string[] | что может не подойти владельцу, по мнению фильтра: `english` (просят B2), `abroad` (на DOU не отмечено «за кордоном»), `ukraine` (надо быть в Украине), `no_description` (текст не загрузился), `no_python`, `python_plus` (Python только «будет плюсом»), `early_startup` (founding / seed / stealth: такая вакансия не выше review) |
| `copies` | `[{id, source}]` | та же вакансия на других площадках |
| `history` | `[event]` | **B.** журнал статусов, от старых к новым; `[]`, пока событий нет |

Событие журнала (B):

```json
{"id": "5f1c9a02be7d", "occurred_at": "2026-11-02T09:41:00Z", "recorded_at": "2026-11-03T08:15:12Z",
 "from": "replied", "to": "interview", "actor": "ai",
 "reason_code": null, "suggested_code": null, "reason": "Приглашение на тех. интервью 4.11",
 "evidence": "gmail:18c2f0a1b2", "approximate": false, "undo_of": null, "cause": null}
```

- `occurred_at` — когда это **произошло** (дата письма; клиент передаёт, по умолчанию — момент
  записи); `recorded_at` — когда бот записал. Аналитика — по `occurred_at`.
- `approximate: true` — время события — догадка: запись без `occurred_at`, нажатие кнопки исхода
  (нажали позже, чем пришло письмо), восстановленные события. В метрики времени не входят.
- `actor`: `user` (владелец: кнопка или его просьба через клиента) | `ai` (решение AI) |
  `system` (бот: повторы, отказ по тишине, начальное заполнение журнала). `actor` заявляет
  клиент — это аудит, а не защита.
- `evidence` — откуда известно: id письма Gmail или цитата.
- `undo_of` — `id` события, которое это отменило; `cause` — событие на другой копии, из-за
  которого эта стала повтором.

## GET /jobs — список

Сортировка всегда от новых к старым: `found_at`, затем `id`. Без текста вакансии, если не
попросить `with_description=true` (тогда у каждой есть `description`, как в полной форме).

| Параметр | По умолчанию | Смысл |
|---|---|---|
| `status` | все, кроме `duplicate` | статусы через запятую |
| `tier` | все, кроме `filtered_out` | через запятую; `filtered_out` — только явно |
| `source` | все | площадки через запятую |
| `any` / `all` / `none` / `where` | — | поиск по словам |
| `company` | — | подстрока в названии компании, без учёта регистра |
| `url` | — | ссылка на вакансию (из письма); сравнивается без `www.`, параметров и хвостового `/` |
| `source_id` | — | id вакансии на самой площадке (как в её ссылке) |
| `search` | — | часть URL поиска, который нашёл вакансию, без учёта регистра |
| `filter_reason` | — | причины фильтра через запятую (`senior,office`); без `tier` ищет среди всех, не только дошедших |
| `reason_code` | — | коды причин через запятую (`english,experience`) |
| `with_description` | `false` | добавить полный текст каждой вакансии |
| `ai_fit` | — | **B.** `yes,maybe,no,none` (`none` = AI ещё не оценивал) |
| `from` / `to` | последние 30 дней | по `found_at` |
| `limit` | 50 | 1–200 |
| `cursor` | — | `next_cursor` прошлой страницы |

Ответ:

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
     "search": "https://djinni.co/jobs/?primary_keyword=Python", "duplicate_of": null}
  ],
  "next_cursor": "eyJmIjoiMjAyNi0xMC0yOFQwOToxMjo0NFoiLCJpIjoiNjcyMGYxYzIifQ"
}
```

`next_cursor: null` — страниц больше нет. Пагинация по ключу (а не offset): вакансии, найденные,
пока клиент листает, не дают дублей и пропусков, а попадут на первую страницу следующего запроса.

Типовые запросы:

- свежие без решения: `?status=new&from=2026-10-27`
- письмо пришло от компании: `?company=acme&status=applied,replied,interview` или `?url=<ссылка из письма>`
- про AI в названии: `?any=ai,llm,ml,genai,agentic&where=title`
- ждут ручного просмотра (сводка 👀): `?tier=review&status=new&from=<2 недели назад>`
- отклики с текстами для анализа: `?status=applied,replied,interview,offer,rejected_by_employer&with_description=true`

## GET /jobs/{id} — одна вакансия

Полная форма. `404 not_found`, если такой нет.

## GET /jobs/funnel — воронка

Считает бот. По умолчанию (`by=found`) когорта — вакансии, **найденные** в `[from, to)`;
`by=event` — события журнала в этом периоде, см. ниже. «Откликов в октябре» здесь —
отклики на вакансии, найденные в октябре. Повторы (`duplicate`) в воронку не входят (одна
вакансия — одно решение), их число — отдельно в `repeats`.

| Параметр | По умолчанию | Смысл |
|---|---|---|
| `from` / `to` | последние 30 дней | по `found_at` (`by=event` — по `occurred_at` событий) |
| `by` | `found` | `found \| event` |
| `group_by` | `none` | `none \| source \| stack \| week \| tier \| search` |
| `source`, `any`, `all`, `none`, `where`, `company`, `search` | — | те же фильтры, что у списка |

- `group_by=stack`: одна вакансия попадает во все свои технологии, поэтому сумма групп больше
  итога.
- `group_by=week`: ISO-неделя по времени `Europe/Berlin`, ключ `2026-W44`.
- `group_by=search`: эффективность поисков бота. `key` — URL поиска (`(unknown)` для вакансий
  до 06.10.2026), `label` — он же коротко («Djinni · Python»). У остальных группировок
  `label` = `key`.

Ответ:

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

- `found` — найдено без повторов; `repeats` — повторы, в остальные числа не входят.
- `surfaced` — дошли до Telegram (`tier` не `filtered_out`); `decided` — из них со статусом не `new`.
- `tiers` — сколько найденного попало в каждый `tier`.
- `opened` — сколько дошедших владелец открыл по ссылке; `clicks` — всего переходов.
- `reached.X` — дошли **до этапа X или дальше**. Отказ работодателя — это ответ, поэтому он
  входит в `replied`; кроме `no_response` — тишина не ответ, такой отклик остаётся в `applied`.
- `rejected_after` — на каком этапе отказали. `unknown` — отказ записан до журнала (B).
- `by` — `found`; `journal` — записи журнала владельца за период (см. `GET /jobs/journal`),
  `[]` — изменений не было. Хранилище журнала недоступно → `journal: null` и
  `journal_error: "unavailable"`: это «неизвестно», а не «изменений не было»; цифры воронки от
  журнала не зависят и приходят как обычно.

### `by=event` — что произошло за период (B)

Когорта — события `history`, чей `occurred_at` (когда **произошло**, не когда записано) в
`[from, to)`. «Сколько откликов я сделал в октябре», «сколько интервью было на неделе».

**Отменённое не считается.** Событие и его отмена (`undo_of`) выпадают оба, вместе с повторами,
которые событие сделало на других копиях (`cause`): тестовый PATCH или исправленная ошибка AI в
числах не остаются.

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
               "kind": "cv", "text": "CV: AI-проекты наверх", "actor": "user"}],
  "journal_error": null
}
```

- `events` — сколько событий в периоде; `entered.X` — сколько из них привели в статус X;
  `transitions` — переходы «откуда → куда», частые сверху.
- `applied` — откликов в периоде; `reached.X` — из них дошли до этапа X или дальше **к сегодняшнему
  дню** (их последующие события, в том числе после `to`); отказ `no_response` — не ответ.
  `reply_rate` / `interview_rate` — доли.
- `rejections` — отказы работодателя в периоде: этап, на котором отказали (`from` события), → код
  причины → число. Код `unknown` — отказ без кода.
- `time_to_reply` — часы от отклика до **первого** ответа работодателя (`replied`, `interview`,
  `offer` или отказ), период — по времени ответа. Не входят: события `approximate` (с любой
  стороны) и отказ `no_response` (тишина — не ответ). `null`, когда пар нет.
- `group_by` — те же значения; `week` — неделя **события** (у `reached` — неделя отклика,
  у `time_to_reply` — неделя ответа).
- Это корреляция, не эксперимент: при десятках откликов и нескольких изменениях подхода подряд
  причину по `journal` не отделить.
- `apply_rate` = `reached.applied / decided` — доля «откликнулся» среди решений; `reply_rate` =
  `reached.replied / reached.applied`; `median_hours_to_decision` — медиана часов от нахождения
  до решения. `null`, когда делить не на что.

## GET /jobs/digest — недельный дайджест

Те же числа, что бот присылает в Telegram по пятницам: рынок и решения владельца за `days`
дней (1–180, по умолчанию 7) с выводами. В отличие от воронки, решения здесь считаются **по
моменту решения** (нажатия кнопки), а рынок — по вакансиям его области (без чужого стека и
не-разработческих ролей).

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

- `market` — что просят: `in_field` / `in_field_prev` (вакансий области, эта и прошлая неделя),
  `surfaced`, `reach_share`, `by_tier`, `years` / `english` / `work_format` (распределения),
  `top_tech` (`share` и `delta` к прошлой неделе), `salary` (`median`, `low`, `high`, `n`),
  `applicants`, `blockers` (что не пускает: `senior`, `experience`, `english`, `office`, ...).
- `me` — решения: `decisions` / `prev`, `apply_rate` / `apply_rate_prev`, `funnel` (`found`,
  `surfaced`, `opened`, `applied`), `pending`, `by_platform`, `outcomes` (что вышло из откликов,
  по площадкам), `by_tier_rate`, `searches` (лучшие и худшие поиски за 4 недели),
  `dead_searches`, `mismatch_reasons`, `not_interested_reasons`, `filter_misses`,
  `avg_hours_to_action` (медиана), `applied_tech`.
- `market_insights` / `my_insights` — до 5 выводов: `{kind, ...числа}`. `kind`: рынок —
  `seniority_wall`, `english_gate`, `tech_rising`, `tech_falling`, `volume`, `competition`;
  владелец — `platform_gap`, `tiers`, `main_gap`, `filter_miss`, `speed`, `backlog`,
  `dead_search`, `trend`.
- `silent_sources` — площадки, которые бот ищет, но за период они не дали ни одной вакансии
  (сломался разбор или блокировка).
- Доли — от 0 до 1. Число, за которым слишком мало данных, — `null`.
- База недоступна → `503 storage_unavailable` (а не нули).

## Журнал владельца (B)

Изменения подхода — новое CV, другое письмо, стратегия, рынок — с датой, чтобы видеть их на той же
шкале времени, что и цифры воронки.

`POST /jobs/journal` → `201`:

```json
{"kind": "cv", "text": "CV: AI-проекты наверх, убрал фриланс", "occurred_at": "2026-10-14T09:00:00Z"}
```

| Поле | Обязательно | Смысл |
|---|---|---|
| `kind` | да | `cv \| letter \| strategy \| market \| other` |
| `text` | да | что изменилось и зачем, 1–2000 символов |
| `occurred_at` | нет | когда изменение сделано; по умолчанию — сейчас; в будущем → `400` |
| `actor` | нет | `user` (по умолчанию) \| `ai` |

Ответ — запись: `{id, occurred_at, recorded_at, kind, text, actor}`. Неизвестное поле → `400`.

`GET /jobs/journal?from=&to=` → `{"items": [запись, ...]}` — записи периода по `occurred_at`, от
старых к новым; по умолчанию последние 30 дней. Те же записи приходят в `journal` воронки.

## Отказ по тишине (B)

Раз в сутки (10:00 по `Europe/Berlin`) бот сам переводит отклик в отказ: `applied` и в `history`
нет событий 21 день (`NO_RESPONSE_DAYS`) → `rejected_by_employer`, `reason_code: no_response`,
`actor: system`, тихая правка сообщения без реплики. `occurred_at` отказа — последнее событие + 21
день (когда тишина набрала срок), а не день проверки. Проверка включается разовой миграцией тишины
у старых откликов; до неё не делает ничего. Отменить — как любое изменение: PATCH или
кнопка исхода. Клиенту `no_response` ставить можно, но обычно незачем.

## PATCH /jobs/{id}/status — сменить статус (B)

```json
{"status": "rejected_by_employer", "expected_status": "applied", "actor": "ai",
 "reason_code": "salary", "reason": "Бюджет до $1500, просил $2500",
 "evidence": "gmail:18c2f0a1b2", "occurred_at": "2026-11-02T09:41:00Z"}
```

| Поле | Обязательно | Смысл |
|---|---|---|
| `status` | да | новый статус; `blocked` и `duplicate` → `400` |
| `expected_status` | да | какой статус клиент видел. Не совпал → `409 status_conflict` с `current_status` |
| `actor` | да | `ai \| user`; `system` → `400` (его ставит только бот) |
| `reason_code` | нет | из словаря **нового** статуса (`GET /jobs/reasons`); неизвестный, `muted` или код у статуса без словаря → `400` |
| `suggested_code` | с `other` | какой код бы подошёл, `snake_case`; `other` без него → `400`, без `other` → `400` |
| `reason` | нет | свободный текст, до 2000 символов |
| `evidence` | у `ai` | id письма Gmail или цитата, до 1000 символов; `actor: ai` без него → `400` |
| `occurred_at` | нет | когда это произошло; по умолчанию — сейчас, и тогда событие `approximate`. В будущем или раньше `found_at` → `400` |

Неизвестное поле в теле → `400` (опечатка не должна пройти как «причины нет»).

- Любой переход между разрешёнными статусами допустим, в том числе откат (`interview` →
  `replied`). Откат — это новое событие, история не переписывается.
- Тот же статус с той же причиной → `200`, `"changed": false`, события нет — в том числе когда
  клиент повторяет запрос, ответ на который потерял (`expected_status` тогда уже старый). Тот же
  статус с **другой** причиной → новое событие. Поля причины, которых нет в теле, при том же
  статусе остаются как были; при смене статуса — пустые.
- Решение по одной копии решает за группу: ждущие копии становятся `duplicate` (события
  `actor: system` с `cause`). Вакансия-повтор или копия группы, где решение уже есть, →
  `409 is_duplicate` с `duplicate_of`: менять статус там.
- После записи бот правит сообщение о вакансии в Telegram. Ошибка Telegram статус не откатывает.

Ответ `200`:

```json
{"changed": true, "job": { "...": "полная форма" }, "telegram": "queued"}
```

`telegram`: `queued` — правка и/или реплика поставлены в очередь отправки | `skipped` —
показывать нечего: сообщения нет, а изменение не от AI. Что Telegram сделал на самом деле,
видно в логах бота; статус сохранён в любом случае.

## GET /jobs/reasons — коды причин (B)

```json
{"statuses": {
  "rejected_by_employer": [{"code": "no_reason", "description": "Отказ без причины: шаблонное «выбрали другого кандидата», …"}],
  "mismatch": [{"code": "experience", "description": "Владелец не проходит по опыту или уровню"}],
  "not_interested": [{"code": "role", "description": "Не та роль"}]
}}
```

Только коды, которые клиент может поставить (`muted` — кнопка, его здесь нет). Список
меняется с релизами бота: новый код появляется здесь, события до него остаются `other` с
`suggested_code`.

## Telegram при изменениях через API (B)

- **Статус — правка всегда.** Сообщение вакансии правится тихо: строка статуса, кнопки под
  новый статус, пометка «🤖» для `actor: ai`.
- **Реплика — на каждое изменение от AI.** Следом за правкой бот отправляет короткий
  ответ-реплику на сообщение вакансии («🤖 AI: Откликнулся → **Отказ** (зарплата)», вакансия,
  причина) с кнопкой «↩️ Отменить». Со звуком — только `replied`, `interview`, `offer`; остальное
  приходит без звука. Изменения от `user` через API — только тихая правка.
- **Нет сообщения** (вакансия до хранения `message_id`, сводка 👀, сообщение удалено): новое
  сообщение вакансии не шлётся; реплика от AI приходит отдельным сообщением с «↩️ Отменить» и
  ссылкой на вакансию.

  Старые сообщения бот не удаляет: Telegram разрешает удалять только сообщения младше 48 часов.
- **«↩️ Отменить»** возвращает статус и причину, что были до события, и копии, которые оно
  сделало повторами; в журнале — новое событие с `undo_of`. Отменить можно только последнее
  событие и только пока статус тот, что оно поставило; иначе — «уже изменено», ничего не меняется.
- **Очередь.** Правки и реплики уходят через одного отправителя: по одной, пауза на `429`
  (`retry_after`), повтор с растущей паузой на таймаут и `5xx`. Очередь хранится в базе и
  переживает перезапуск бота; ответ API Telegram не ждёт.
- Нажатие кнопок в Telegram работает как раньше и реплик не порождает. Если статус успели
  изменить, пока кнопка висела, бот отвечает «Статус уже изменён» и обновляет сообщение.

## Открыто

Пока не сделано; добавится без поломок (новое значение параметра, новый эндпоинт).

- **B:** `PUT /jobs/{id}/ai_verdict` — оценка AI `{fit: yes|maybe|no, reason, at}` и поле
  `ai_verdict` в вакансии; статус не меняет. Отложено.
