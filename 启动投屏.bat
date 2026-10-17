@echo off
chcp 65001 >nul
setlocal

REM KonkaCast 电视投屏控制台 - 一键启动

set "ROOT=%~dp0"
REM 优先用 Windows 自带的 Python Launcher（py -3），回退系统 python
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys" >nul 2>nul || (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 并勾选「Add Python to PATH」。
    pause
    exit /b 1
)

cd /d "%ROOT%"

echo.
echo   正在启动 KonkaCast ...
echo   控制台会自动在浏览器里打开。关掉这个黑窗口就是退出服务。
echo.

REM 走 run.py：出错时会自动把堆栈写进 错误日志.txt，窗口也不闪退
%PY% run.py %*

if errorlevel 1 (
    echo.
    echo   [启动失败] 请截图上面的报错信息。
    pause
)
