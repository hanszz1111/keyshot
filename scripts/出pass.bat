@echo off
chcp 936 >nul
setlocal
title 出结构 pass - AI 白模渲染器
set "PROJ=D:\Dsektop\AI渲染"
set "BLENDER=D:\Dsektop\blender-4.5.0-windows-x64\blender.exe"
set "SCRIPT=%PROJ%\scripts\blender_pass.py"

if "%~1"=="--self-test" goto selftest
if "%~1"=="" goto usage
if not exist "%BLENDER%" goto noblender
if not exist "%SCRIPT%" goto noscript

set "MODEL=%~1"
if "%~2"=="" (set "SKU=%~n1") else (set "SKU=%~2")
if "%~3"=="" (set "VIEW=front") else (set "VIEW=%~3")

echo ============================================================
echo  出结构 pass（Blender 确定性基线）
echo ------------------------------------------------------------
echo   模型 : %MODEL%
echo   SKU  : %SKU%
echo   机位 : %VIEW%
echo ------------------------------------------------------------
echo   输出 : %PROJ%\assets\passes\%SKU%\%VIEW%\
echo ============================================================
echo.

"%BLENDER%" -b -P "%SCRIPT%" -- --model "%MODEL%" --sku "%SKU%" --view "%VIEW%"

echo.
echo 完成。可直接到网页控制台的「投放区」刷新查看。
echo 按任意键关闭。
pause >nul
exit /b 0

:selftest
if not exist "%BLENDER%" goto noblender
echo 自检模式：用内置几何跑通整条 pass 链路（不需要模型）
echo.
"%BLENDER%" -b -P "%SCRIPT%" -- --self-test --out "%PROJ%\outputs\_passtest"
echo.
echo 自检完成，产物在 %PROJ%\outputs\_passtest
pause >nul
exit /b 0

:usage
echo 出结构 pass - 用法
echo ============================================================
echo  方式一：把 3D 模型文件直接拖到本文件上（最简单的用法）
echo.
echo  方式二：命令行
echo      出pass.bat "模型路径" [SKU] [机位]
echo.
echo  机位：front 3q4_left 3q4_right side top detail_keypad detail_window
echo        也认中文：正面 左前 右前 侧面 俯视 按键 透明件
echo.
echo  支持格式：.blend .glb .gltf .obj .stl .fbx
echo  需先转换：.ksp(KeyShot) .stp/.step .3dm(Rhino) .c4d .max
echo            —— 请在原软件里导出为 .glb 或 .obj 再来
echo.
echo  方式三：自检（不需要任何模型）
echo      出pass.bat --self-test
echo ============================================================
pause
exit /b 1

:noblender
echo [错误] 找不到 Blender：
echo   %BLENDER%
echo 请确认 Blender 4.x 已安装，或修改本文件里的 BLENDER 变量。
pause
exit /b 1

:noscript
echo [错误] 找不到脚本：
echo   %SCRIPT%
pause
exit /b 1
