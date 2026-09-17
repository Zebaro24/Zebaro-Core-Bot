# `scripts/` — тулинг Zebaro-Core-Bot

Всё на голом Python из стандартной библиотеки и `.bat` без зависимостей: тулинг должен
работать даже тогда, когда `poetry install` ещё не запускался. Запускать **из корня
репозитория** (bat-файлы сами находят корень).

| Скрипт             | Что делает                                                                                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `gate.py`          | **Единственный чекер.** poetry-lock, black, isort, flake8, mypy, bandit, pip-audit, pytest. Ровно то же самое гоняет CI и CD перед деплоем. Руками чекеры не зовём |
| `release.py`       | Готовит релиз: версия → зеркала в `pyproject.toml` и `src/config.py` → `CHANGELOG` → коммит → тег → одноразовое одобрение. **Не пушит**                            |
| `approve.py`       | Выписывает одноразовый маркер, который разрешает `git push` или пуш тега. Живёт 15 минут, тратится один раз                                                        |
| `dev.bat`          | Локально: `dev` (бот), `dev infra` / `dev stop` (Mongo + Playwright в Docker), `dev gate`, `dev install`                                                           |
| `prod.bat`         | Прод по SSH: `prod health`, `prod ps`, `prod logs [c] [since]`, `prod state`, `prod restart <c>`, `prod` (шелл)                                                    |
| `start-claude.bat` | Открыть Claude Code в корне проекта через Windows Terminal (там Shift+Enter даёт перенос строки). Двойной клик или ярлык на панели задач                            |

## Шпаргалка

```bash
python scripts/gate.py                     # всё, ровно как CI
python scripts/gate.py --lint              # линт и типы, без тестов — быстро, по ходу работы
python scripts/gate.py --tests             # только тесты
python scripts/gate.py --strict            # + покрытие (перед релизом, так гоняет CI)
python scripts/gate.py --fix               # сначала black + isort, потом гейт
python scripts/gate.py --only pytest -- tests/interfaces/test_telegram_webhook.py
python scripts/gate.py --list              # какие проверки вообще есть

python scripts/release.py --bump minor --dry-run
```

```bat
scripts\dev.bat infra                      :: Mongo + Playwright
scripts\dev.bat                            :: бот локально (polling, из .env)
scripts\prod.bat health                    :: жив ли прод
scripts\prod.bat logs                      :: логи бота за сутки
scripts\prod.bat logs zebaro-core-playwright 1h
```

## Прод

`zebaro@server.zebaro.dev`, системный ключ `id_ed25519`, compose в `/srv/zebaro-core`,
публичный адрес `https://bot.zebaro.dev`. Адрес берётся из переменных `PROD_USER` /
`PROD_HOST` (один раз `setx`), `PROD_URL` переопределяет публичный адрес.

**Заход на сервер — действие наружу.** Спрашивай перед первым `ssh` в задаче.
`prod health` бьёт по публичному HTTP и в сервер не заходит — им можно проверять свободно.

Процесс, гейт и конвенции — в `.claude/docs/` (или скилл `/playbook`).
