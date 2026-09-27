@echo off

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
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo   ============================================================
echo     AI 白模渲染器 · 控制台
echo   ============================================================
echo.

set "PYEXE="
set "PYARGS="
set "MANAGED=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"

if exist "%MANAGED%" (
  set "PYEXE=%MANAGED%"
  goto :gotpy
)

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=py"
  set "PYARGS=-3"
  goto :gotpy
)

python -c "import sys" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=python"
  goto :gotpy
)

goto :nopy


:gotpy
echo   解释器   %PYEXE% %PYARGS%
echo.
echo   正在启动服务，就绪后会自动打开浏览器。
echo   若浏览器没有自动打开，请手动访问下面显示的地址。
echo.
echo   ------------------------------------------------------------
"%PYEXE%" %PYARGS% "%~dp0web\server.py"
set "RC=%errorlevel%"
echo   ------------------------------------------------------------
echo.
echo   服务已退出（返回码 %RC%）。
if not "%RC%"=="0" echo   上面若有报错信息，请截图发我。
echo.
echo   按任意键关闭本窗口...
pause >nul
exit /b %RC%


:nopy
echo   [错误] 没有找到可用的 Python 运行环境。
echo.
echo   请按以下任一方式解决：
echo.
echo     1^) 打开 https://www.python.org/downloads/ 下载安装 Python 3.11 或更新版本，
echo        安装时务必勾选 "Add python.exe to PATH"，装好后重新双击本文件。
echo.
echo     2^) 如果电脑里已经装过 Python，请打开「设置 - 应用 - 高级应用设置 -
echo        应用执行别名」，把 python.exe 和 python3.exe 的 Microsoft Store
echo        别名开关关掉，然后重试。
echo.
echo   还是不行的话，把本窗口截图发我。
echo.
echo   按任意键关闭本窗口...
pause >nul
exit /b 1
