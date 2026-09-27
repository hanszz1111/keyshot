@echo off
chcp 936 >nul

echo ============================================================
echo   [已归档] 这是历史版本，已被 启动全部.bat 取代
echo ------------------------------------------------------------
echo   本文件位于 docs\archive\，仅作历史记录保留。
echo   请改用项目根目录的：
echo     启动全部.bat    （启动，经计划任务持久化）
echo     停止服务.bat    （停止）
echo.
echo   与当前方案的两处关键差异：
echo     1 ^) 项目根路径：本脚本写的是外层 AI渲染，
echo        实际真实根是 AI渲染\AI渲染
echo     2 ^) 启动方式：本脚本用 start 起进程，关窗口就停；
echo        v2.3 起改为 Windows 计划任务承载，跨会话存活
echo ============================================================
echo.
title AI 白模渲染器 - 一键启动
set "PROJ=D:\Dsektop\AI渲染"
set "PACK=F:\AI-Renderer\packs\ComfyUI_windows_portable"
set "PYEXE=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo ============================================================
echo   AI 白模渲染器 - 一键启动
echo ------------------------------------------------------------
echo   1. ComfyUI 出图引擎   http://127.0.0.1:8188
echo   2. 网页控制台         http://127.0.0.1:8765
echo ============================================================
echo.

if not exist "%PACK%\python_embeded\python.exe" goto nopack

echo [1/2] 启动 ComfyUI（8GB 适配 --lowvram，首次要等 30-60 秒）...
start "ComfyUI" /d "%PACK%" "%PACK%\python_embeded\python.exe" -s ComfyUI\main.py --windows-standalone-build --lowvram

echo [2/2] 启动网页控制台...
start "控制台" /d "%PROJ%\web" "%PYEXE%" server.py

echo.
echo 等待服务起来（约 8 秒）...
timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:8765

echo.
echo 已启动。控制台右上角会显示 ComfyUI 在线状态：
echo   绿色 = 在线，可以直接点「送到 ComfyUI 出图」
echo   红色 = 离线，请检查 ComfyUI 窗口有没有报错
echo.
echo 关闭对应的两个黑窗口即停止服务。
pause
exit /b 0

:nopack
echo [错误] 找不到 ComfyUI 便携版：
echo   %PACK%
echo.
echo 请先双击 scripts\下载模型.bat 下载，并解压
echo   F:\AI-Renderer\packs\ComfyUI_windows_portable_nvidia.7z
echo.
pause
exit /b 1
