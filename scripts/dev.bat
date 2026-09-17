@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
rem dev.bat - run a piece of Zebaro-Core-Bot locally, without remembering the command.
rem
rem   dev                the bot (Telegram polling + webhooks + Discord, from .env)
rem   dev infra          MongoDB + Playwright in Docker, ports published to localhost
rem   dev stop           stop them (data in mongo_db/ survives)
rem   dev gate [flags]   the quality gate (the same one CI runs)
rem   dev install        poetry install
rem
rem The bot starts and stops MongoDB and Playwright itself through /services, but
rem the containers have to exist first - `dev infra` creates them.

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "CMD=%~1"
if "!CMD!"=="" set "CMD=bot"

rem docker-compose.override.yml publishes 27017 and 9222 to localhost; it is
rem gitignored, so without it the containers run but the local bot cannot reach them.
set "COMPOSE=docker compose -p zebaro-core -f "%ROOT%\docker-compose.yml""
if exist "%ROOT%\docker-compose.override.yml" set "COMPOSE=!COMPOSE! -f "%ROOT%\docker-compose.override.yml""

if /i "!CMD!"=="help" (
    echo dev              - the bot
    echo dev infra^|stop   - MongoDB + Playwright in Docker
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
        echo       локальный бот не достучится до Mongo и Playwright.
    )
    !COMPOSE! up -d zebaro-core-db zebaro-core-playwright
    goto :end
)
if /i "!CMD!"=="stop" (
    !COMPOSE! stop zebaro-core-db zebaro-core-playwright
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

:end
endlocal
