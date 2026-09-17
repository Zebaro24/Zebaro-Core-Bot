@echo off
REM Open Claude Code at the Zebaro-Core-Bot root, so CLAUDE.md, .claude/ and the
REM whole source tree are in scope from the first message.
REM
REM Launched inside Windows Terminal (wt.exe) on purpose: there Shift+Enter gives
REM a real newline in the prompt, which a classic console window does not.
REM Falls back to a plain PowerShell window if Windows Terminal is missing.
REM
REM Double-click it, or pin a shortcut to it on the taskbar / Start.

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

where wt.exe >nul 2>nul
if errorlevel 1 goto fallback

wt.exe -d "%ROOT%" --title Zebaro-Core-Bot powershell -NoLogo -NoExit -ExecutionPolicy Bypass -Command claude
goto :eof

:fallback
start "Zebaro-Core-Bot — Claude Code" powershell -NoLogo -NoExit -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%ROOT%'; claude"
