@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
rem prod.bat - the production server, without long ssh lines.
rem
rem Target: set PROD_USER and PROD_HOST once, as user environment variables
rem (the same ones Bento's prod.bat uses). There is no guessed default: the wrong
rem one silently tries the wrong machine. `prod health` needs neither - it goes
rem over public HTTP.
rem
rem   prod                    interactive shell on the server
rem   prod health             GET /health on the public address
rem   prod ps                 the bot's containers and their uptime
rem   prod logs [c] [since]   docker logs with timestamps (bot, 24h by default)
rem   prod state              services.json - which services are on
rem   prod restart <c>        restart one container  (touches prod - ask first)
rem   prod <anything...>      run the rest as a raw command on the server
rem
rem Containers: zebaro-core-bot, zebaro-core-db, zebaro-core-playwright.
rem Compose: /srv/zebaro-core. SSHing in is an outward action - confirm first.

if "%PROD_URL%"=="" set "PROD_URL=https://bot.zebaro.dev"
set "TARGET=%PROD_USER%@%PROD_HOST%"
set "CMD=%~1"

if "%PROD_HOST%"=="" goto :noserver
if "%PROD_USER%"=="" goto :noserver
goto :dispatch

:noserver
if /i "%~1"=="health" goto :dispatch
if /i "%~1"=="help" goto :dispatch
echo Не задан адрес сервера. Один раз:
echo     setx PROD_USER zebaro
echo     setx PROD_HOST server.zebaro.dev
echo и открой терминал заново. Те же значения лежат в GitHub - Settings -
echo Environments - prod как секреты SERVER_USER и SERVER_HOST.
echo.
echo `prod health` работает и без них - он идёт по публичному HTTP.
goto :end

:dispatch
if "!CMD!"=="" (
    echo [prod] ssh !TARGET!
    ssh !TARGET!
    goto :end
)

if /i "!CMD!"=="help" (
    echo prod                    - shell on !TARGET!
    echo prod health             - GET !PROD_URL!/health
    echo prod ps                 - containers and uptime
    echo prod logs [c] [since]   - docker logs ^(bot, 24h by default^)
    echo prod state              - services.json on the server
    echo prod restart ^<c^>        - restart one container
    echo prod ^<cmd...^>           - raw command on the server
    goto :end
)

if /i "!CMD!"=="health" (
    echo [prod] !PROD_URL!/health
    curl -sS -m 10 "!PROD_URL!/health" & echo.
    goto :end
)

if /i "!CMD!"=="ps" (
    ssh !TARGET! "docker ps -a --filter name=zebaro-core --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'"
    goto :end
)

if /i "!CMD!"=="logs" (
    set "CONTAINER=%~2"
    if "!CONTAINER!"=="" set "CONTAINER=zebaro-core-bot"
    set "SINCE=%~3"
    if "!SINCE!"=="" set "SINCE=24h"
    echo [prod] docker logs !CONTAINER! --since !SINCE! --timestamps
    ssh !TARGET! "docker logs !CONTAINER! --since !SINCE! --timestamps"
    goto :end
)

if /i "!CMD!"=="state" (
    ssh !TARGET! "cat /srv/zebaro-core/state/services.json 2>/dev/null || echo 'no state file yet - every service is on by default'"
    goto :end
)

if /i "!CMD!"=="restart" (
    if "%~2"=="" ( echo Usage: prod restart ^<container^>  & goto :end )
    echo [prod] docker restart %~2
    ssh !TARGET! "docker restart %~2"
    goto :end
)

echo [prod] raw: !TARGET! %*
ssh !TARGET! %*

:end
endlocal
