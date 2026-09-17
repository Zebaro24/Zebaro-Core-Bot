---
name: idea
description: Write a finding into _ideas/ — something noticed in passing that is not the current task. Use the moment you stumble over it, not later.
user-invocable: true
allowed-tools: Read, Write, Edit, Glob
---

Everything you notice that is **not the task in front of you** goes here: a rough edge in
the tooling, a doc that lies, a bug you walked past, a job source worth adding, a decision
that needs taking.

`_ideas/` is the owner's personal desk, outside git on purpose.

## The rule

> **Never decide alone, and never let it evaporate.** Ask the owner in one line whether
> it is worth doing now. "Yes" → do it. "No", or you could not ask → write it here.

Write it **the moment you stumble**: an hour later you remember the conclusion and not the
place you got stuck, and the place is what makes it findable.

## How

1. Name it `<area>-<short-slug>.md`, area one of `tooling` `jobs` `tg` `infra` `docs` `process`.
2. Russian — personal notes, not code. Three short sections:
   - **Что** — one or two sentences.
   - **Как это вылезло** — the concrete moment: command, expected, got, `file:line`.
     "Парсер кривой" cannot be checked; "`listeners/dou.py:31` берёт дату из `span.date`,
     а на странице 17.09 её нет" can.
   - **Что решить до того, как это станет задачей** — the open question.
3. Tell the owner in one line that you wrote it.

When it closes (done, or decided against) — delete the file and add a dated line to
`_ideas/CLOSED.md`. `_ideas/` lists **open** questions only.
