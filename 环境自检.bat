@echo off
chcp 65001 >nul
setlocal

REM KonkaCast 环境自检 —— 报错时第一个跑这个

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

%PY% tools\check_env.py

echo.
echo   报告同时保存在 错误日志.txt
echo.
pause
