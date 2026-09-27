@echo off
chcp 936 >nul
title AI 白模渲染器 - 下载模型与运行时
setlocal

set "PS1=%~dp0download_models.ps1"

if not exist "%PS1%" goto nops1

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
if errorlevel 1 goto failed
goto end

:nops1
echo.
echo [错误] 找不到 download_models.ps1
echo        请确认它和本文件在同一个 scripts 目录下。
echo.
pause
goto end

:failed
echo.
echo [提示] 下载未全部完成。
echo        再次双击本文件即可续传，已下好的部分不会重下。
echo.
pause
goto end

:end
endlocal
