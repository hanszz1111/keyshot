# -*- coding: utf-8 -*-
"""生成 停止服务.bat —— 必须 CRLF + cp936，零裸 LF（cmd 否则报“此时不应有”闪退）。"""
import os

BAT = "\n".join([
    "@echo off",
    "setlocal EnableExtensions",
    'cd /d "%~dp0"',
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\stop_all.ps1"',
    'set "RC=%ERRORLEVEL%"',
    'if not "%RC%"=="0" (',
    "  echo.",
    "  echo Stop needs attention. Read the message above.",
    "  pause",
    ")",
    "exit /b %RC%",
    "",
])

target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "停止服务.bat")
target = os.path.abspath(target)
data = BAT.replace("\n", "\r\n").encode("cp936")
with open(target, "wb") as fh:
    fh.write(data)
print("written", target, len(data), "bytes")

check = open(target, "rb").read()
print("CRLF", check.count(b"\r\n"), "bare LF", check.count(b"\n") - check.count(b"\r\n"))
check.decode("cp936")
print("cp936 OK")
