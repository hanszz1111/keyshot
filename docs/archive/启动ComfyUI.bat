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
title ComfyUI - AI 白模渲染器
set "PACK=F:\AI-Renderer\packs\ComfyUI_windows_portable"

if not exist "%PACK%\python_embeded\python.exe" goto nopack

echo ============================================================
echo  ComfyUI - AI 白模渲染器
echo  启动参数：--lowvram（适配 8GB 显存）
echo  启动后浏览器打开：http://127.0.0.1:8188
echo  关闭本窗口即停止服务。
echo ============================================================
echo.

cd /d "%PACK%"
".\python_embeded\python.exe" -s ComfyUI\main.py --windows-standalone-build --lowvram

echo.
echo ComfyUI 已退出。
pause
exit /b 0

:nopack
echo [错误] 找不到 ComfyUI 便携版：
echo   %PACK%
echo.
echo 请先：
echo   1) 双击 scripts\下载模型.bat 下载运行时与模型
echo   2) 解压 F:\AI-Renderer\packs\ComfyUI_windows_portable_nvidia.7z
echo.
pause
exit /b 1
