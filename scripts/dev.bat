@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
rem dev.bat - run a piece of Zebaro-Core-Bot locally, without remembering the command.
rem
rem   dev                the bot (Telegram polling + webhooks + Discord, from .env)
rem   dev infra          PostgreSQL + Playwright in Docker, ports published to localhost
rem   dev stop           stop them (data in data/postgres/ survives)
rem   dev gate [flags]   the quality gate (the same one CI runs)
rem   dev install        poetry install
rem
rem The bot starts and stops Playwright itself through /services, but the container
rem has to exist first - `dev infra` creates it. PostgreSQL runs until `dev stop`.
rem The local bot: DATABASE_URL=postgresql+asyncpg://zebaro_core:local@localhost:5433/zebaro_core
rem in .env (or nothing: SQLite in zebaro.db).

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "CMD=%~1"
if "!CMD!"=="" set "CMD=bot"

rem docker-compose.override.yml publishes PostgreSQL (5433 - 5432 is often taken) and 9222; it is
rem gitignored, so without it the containers run but the local bot cannot reach them.
rem The project name (zebaro-core-bot) comes from the file itself; state goes to .\data.
rem Moving from the old local layout, once: docker compose -p zebaro-core down,
rem then  mkdir data ^& move mongo_db data\mongo  (otherwise the local bot starts on an empty DB).
set "COMPOSE=docker compose -f "%ROOT%\docker-compose.yml""
if exist "%ROOT%\docker-compose.override.yml" set "COMPOSE=!COMPOSE! -f "%ROOT%\docker-compose.override.yml""

if /i "!CMD!"=="help" (
    echo dev              - the bot
    echo dev infra^|stop   - PostgreSQL + Playwright in Docker
    echo dev gate [flags] - the quality gate
    echo dev install      - poetry install
    goto :end
)

if /i "!CMD!"=="bot" (
    pushd "%ROOT%" && poetry run python -m src.main & popd
    goto :end
)
if /i "!CMD!"=="infra" (
    if not exist "%ROOT%\docker-compose.override.yml" (
        echo [dev] docker-compose.override.yml нет - порты наружу не проброшены,
        echo       локальный бот не достучится до PostgreSQL и Playwright.
    )
    call :compose_env
    !COMPOSE! up -d zebaro-core-pg zebaro-core-playwright
    goto :end
)
if /i "!CMD!"=="stop" (
    call :compose_env
    !COMPOSE! stop zebaro-core-pg zebaro-core-playwright
    goto :end
)
if /i "!CMD!"=="gate" (
    python "%ROOT%\scripts\gate.py" %2 %3 %4 %5 %6
    goto :end
)
if /i "!CMD!"=="install" (
    pushd "%ROOT%" && poetry install & popd
    goto :end
)

echo Unknown command: !CMD!.  Try: dev help
goto :end

:compose_env
rem Compose checks every required value of the file, also of services `infra` does not start, and the
rem bot's .env must not carry them (its settings refuse unknown keys): local stand-ins, unless set.
rem Only for compose - the bot itself (`dev`) never sees them.
for %%V in (TELEGRAM_BOT_TOKEN TELEGRAM_ADMIN_ID DISCORD_BOT_TOKEN GH_APP_ID GH_APP_KEY GH_WEBHOOK_SECRET WEBHOOK_URL WG_PASSWORD) do (
    if not defined %%V set "%%V=local"
)
if not defined POSTGRES_PASSWORD set "POSTGRES_PASSWORD=local"
exit /b 0

:end
endlocal
