#!/usr/bin/env python3
"""notify-windows - a native Windows toast when the owner is actually needed.

Deliberately quiet. Exactly two situations raise a toast:

  Stop                                      -> the task is finished, your turn
  PreToolUse(AskUserQuestion|ExitPlanMode)  -> blocked on a question or a plan

Nothing else. No per-tool chatter, no permission pings, no "still working".
A notifier that fires on everything gets muted within a day, and then it is
worse than having none.

How it works: builds the toast XML here (properly escaped), hands it to a
detached PowerShell via environment variables, and returns immediately. The
hook itself never waits for the toast -- a slow hook stalls the whole turn.

Uses the WinRT toast API that ships with Windows 10/11. No modules to install,
stdlib only. Always exits 0: a notifier must never fail a turn.

Manual test:
  echo '{"hook_event_name":"Stop","cwd":"D:/Projects/1-Active/Zebaro-Core-Bot"}' | python .claude/hooks/notify-windows.py
"""
import json
import os
import subprocess
import sys
from xml.sax.saxutils import escape

# The AppId decides which name and icon Windows shows above the toast. This is
# the built-in PowerShell identity: it is always registered, so the toast
# always appears. A made-up AppId is silently dropped by the shell.
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

PS_SHOW = (
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
    "ContentType=WindowsRuntime]>$null;"
    "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,"
    "ContentType=WindowsRuntime]>$null;"
    "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$x.LoadXml($env:ZCB_TOAST_XML);"
    "$t=New-Object Windows.UI.Notifications.ToastNotification $x;"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "$env:ZCB_TOAST_APPID).Show($t)"
)


def toast(title, body):
    """Fire a toast and return at once. Never raises."""
    if os.name != "nt":
        return
    xml = (
        '<toast activationType="protocol" launch="">'
        '<visual><binding template="ToastGeneric">'
        "<text>%s</text><text>%s</text>"
        "</binding></visual>"
        '<audio src="ms-winsoundevent:Notification.Default"/>'
        "</toast>"
    ) % (escape(title), escape(body))

    env = dict(os.environ, ZCB_TOAST_XML=xml, ZCB_TOAST_APPID=APP_ID)
    args = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-Command", PS_SHOW,
    ]
    # DETACHED_PROCESS | CREATE_NO_WINDOW -- no console flash, no waiting.
    flags = 0x00000008 | 0x08000000
    try:
        subprocess.Popen(
            args, env=env, creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
    except Exception:
        pass


def project(data):
    cwd = (data.get("cwd") or "").rstrip("/\\")
    return os.path.basename(cwd) or "Zebaro-Core-Bot"


def main():
    try:
        raw = "" if sys.stdin.isatty() else sys.stdin.buffer.read().decode("utf-8", "replace")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    event = data.get("hook_event_name") or ""
    tag = project(data)

    if event == "Stop":
        toast("%s — готово" % tag, "Задача закончена, жду тебя.")
        return 0

    if event == "PreToolUse":
        tool = data.get("tool_name") or ""
        ti = data.get("tool_input") or {}
        if tool == "AskUserQuestion":
            qs = [q.get("question", "") for q in (ti.get("questions") or []) if q.get("question")]
            body = qs[0] if qs else "Нужен твой ответ."
            if len(qs) > 1:
                body += "  (+%d)" % (len(qs) - 1)
            toast("%s — вопрос" % tag, body)
        elif tool == "ExitPlanMode":
            toast("%s — план готов" % tag, "Нужно твоё «го».")
    return 0


sys.exit(main())
