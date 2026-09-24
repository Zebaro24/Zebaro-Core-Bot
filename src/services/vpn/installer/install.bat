@echo off
rem Zebaro VPN installer: installs WireGuard for Windows when it is missing or older, imports
rem the person's two tunnels into WireGuard's secure store and turns one on.
rem Built by the bot (services/vpn/installer.py): the __NAMES__ below are filled in per person.
rem Only tunnels named __FULL__ / __LAN__ are touched; any other VPN the person has stays as is.
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Zebaro VPN

rem 7zSD.sfx is a 32-bit program, so on 64-bit Windows this script starts under WOW64, where
rem %ProgramFiles% points to "Program Files (x86)". Restart in the native 64-bit shell.
if defined PROCESSOR_ARCHITEW6432 if exist "%SystemRoot%\Sysnative\cmd.exe" (
    "%SystemRoot%\Sysnative\cmd.exe" /c ""%~f0" %*"
    exit /b !errorlevel!
)

rem The MSI and WireGuard's configuration folder both need administrator rights. fltmc, not
rem "net session": that one fails even elevated when the Server service is disabled, and the
rem script would ask for rights again and again.
fltmc >nul 2>&1
if errorlevel 1 (
    if /i "%~1"=="elevated" (
        echo Не удалось получить права администратора.
        pause
        exit /b 1
    )
    echo Нужны права администратора — подтверди запрос Windows...
    rem The path goes through the environment: a quote in it (a user named O'Neil) would break
    rem the PowerShell string. -Wait: 7zSD deletes this folder as soon as the first copy exits.
    set "ZEBARO_SELF=%~f0"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $p = Start-Process -FilePath $env:ZEBARO_SELF -ArgumentList 'elevated' -Verb RunAs -Wait -PassThru; exit $p.ExitCode } catch { exit 1223 }"
    set "RC=!errorlevel!"
    if "!RC!"=="1223" (
        echo.
        echo Без прав администратора установить не получится. Запусти файл ещё раз и нажми «Да».
        pause
    ) else if not "!RC!"=="0" (
        echo.
        echo Установка не завершилась ^(код !RC!^). Подробности: %TEMP%\Zebaro-VPN-install.log
        pause
    )
    exit /b !RC!
)

set "HERE=%~dp0"
set "WG_VERSION=__WG_VERSION__"
set "FULL=__FULL__"
set "LAN=__LAN__"
set "ACTIVATE=__ACTIVATE__"
set "LOG=%TEMP%\Zebaro-VPN-install.log"
set "WG=%ProgramFiles%\WireGuard\wireguard.exe"
set "CFG=%ProgramFiles%\WireGuard\Data\Configurations"
echo Zebaro VPN %DATE% %TIME% > "%LOG%"

echo.
echo   Zebaro VPN — %FULL%
echo.

rem ---- 1. WireGuard: install when missing, update when older, leave a newer one alone ----
set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" set "ARCH=x86"

set "NEED=1"
if exist "%WG%" (
    for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "try { [version](Get-Item '%WG%').VersionInfo.ProductVersion -ge [version]'%WG_VERSION%' } catch { $false }"`) do (
        if /i "%%v"=="True" set "NEED=0"
    )
)
if "!NEED!"=="1" (
    echo [1/3] Ставлю WireGuard %WG_VERSION% ^(%ARCH%^)...
    msiexec /i "%HERE%wireguard-%ARCH%-%WG_VERSION%.msi" /qn /norestart DO_NOT_LAUNCH=1 /l*v "%TEMP%\Zebaro-VPN-msi.log"
    set "RC=!errorlevel!"
    rem 3010: installed, a reboot would finish it — WireGuard works without one.
    if not "!RC!"=="0" if not "!RC!"=="3010" (
        echo Не удалось установить WireGuard ^(код !RC!^). Подробности: %TEMP%\Zebaro-VPN-msi.log
        echo msiexec !RC! >> "%LOG%"
        pause
        exit /b 1
    )
) else (
    echo [1/3] WireGuard уже установлен — пропускаю.
)

rem ---- 2. The manager service owns the secure store; start it silently if it is not there ----
sc query WireGuardManager >nul 2>&1 || "%WG%" /installmanagerservice >> "%LOG%" 2>&1
for /l %%i in (1,1,30) do if not exist "%CFG%" timeout /t 1 /nobreak >nul
if not exist "%CFG%" (
    echo Служба WireGuard не запустилась. Открой WireGuard вручную и запусти этот файл ещё раз.
    pause
    exit /b 1
)

rem Was one of our tunnels on? Then it goes back on after the update.
set "WAS_ACTIVE="
for %%t in ("%FULL%" "%LAN%") do (
    sc query "WireGuardTunnel$%%~t" 2>nul | find "RUNNING" >nul && set "WAS_ACTIVE=%%~t"
)
rem Is some other WireGuard tunnel on? Then ours is imported, not switched on over it.
set "OTHER_ACTIVE="
for /f "tokens=2 delims=$" %%s in ('sc query type^= service state^= active 2^>nul ^| findstr /b /c:"SERVICE_NAME: WireGuardTunnel$"') do (
    if /i not "%%s"=="%FULL%" if /i not "%%s"=="%LAN%" set "OTHER_ACTIVE=%%s"
)

rem ---- 3. Import: a .conf copied into the folder is encrypted to .conf.dpapi by the manager ----
echo [2/3] Добавляю профили %FULL% и %LAN%...
for %%t in ("%FULL%" "%LAN%") do (
    sc query "WireGuardTunnel$%%~t" >nul 2>&1 && "%WG%" /uninstalltunnelservice "%%~t" >> "%LOG%" 2>&1
    if exist "%CFG%\%%~t.conf.dpapi" del /f /q "%CFG%\%%~t.conf.dpapi" >> "%LOG%" 2>&1
    copy /y "%HERE%%%~t.conf" "%CFG%\%%~t.conf" >nul
    for /l %%i in (1,1,20) do if not exist "%CFG%\%%~t.conf.dpapi" timeout /t 1 /nobreak >nul
    if not exist "%CFG%\%%~t.conf.dpapi" echo   ^(профиль %%~t появится после перезапуска WireGuard^)
)

rem ---- 4. Switch one on, unless the person is using another VPN right now ----
if defined WAS_ACTIVE set "ACTIVATE=!WAS_ACTIVE!"
if defined OTHER_ACTIVE if not defined WAS_ACTIVE (
    echo [3/3] Сейчас включён другой VPN ^(!OTHER_ACTIVE!^) — Zebaro не включаю, он ждёт в списке.
    goto :done
)
echo [3/3] Включаю !ACTIVATE!...
"%WG%" /installtunnelservice "%CFG%\!ACTIVATE!.conf.dpapi" >> "%LOG%" 2>&1 || (
    echo   Включи его сам: WireGuard — !ACTIVATE! — «Подключить».
)

:done
start "" "%WG%"
echo.
echo Готово. В WireGuard два профиля: %FULL% — весь интернет через VPN,
echo %LAN% — только сеть VPN. Переключаются одной кнопкой.
timeout /t 10 >nul
exit /b 0
