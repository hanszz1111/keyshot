@echo off
chcp 936 >nul
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
