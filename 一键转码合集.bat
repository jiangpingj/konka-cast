@echo off
chcp 65001 >nul
title 宫崎骏合集批量转码 H.264
echo ============================================
echo  批量把合集里的 HEVC(H.265) 电影转成 H.264
echo  电视硬解 H.264 流畅,转完投 _x264.mp4 版本
echo  支持断点续转:中途关掉再双击,自动接着转
echo ============================================
echo.

set "ROOT=D:\game\宫丨崎骏合集"
rem 本机 ffmpeg 依赖 ComfyUI 自带的 UCRT 运行时
set "KONKA_CAST_RUNTIME_DIRS=D:\ComfyUI\.ext\Library\bin"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo [错误] 没找到 Python,请先安装 Python 3 或用项目自带环境。
    pause
    exit /b 1
)

%PY% "%~dp0tools\batch_transcode.py" "%ROOT%"
echo.
echo 全部结束,日志见 D:\konka-cast\transcode_log.txt
pause
