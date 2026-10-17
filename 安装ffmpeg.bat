@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM  KonkaCast - ffmpeg 便携版安装（只有"屏幕镜像"功能需要它）
REM  "推送文件/图片/网址" 不需要 ffmpeg，不用装也能用。
REM ============================================================

set "ROOT=%~dp0"
set "BINDIR=%ROOT%bin"
set "TMPZ=%BINDIR%\_ffmpeg.zip"
set "URL=https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip"

if not exist "%BINDIR%" mkdir "%BINDIR%"

if exist "%BINDIR%ffmpeg.exe" (
    "%BINDIR%ffmpeg.exe" -version >nul 2>&1
    if not errorlevel 1 (
        echo ffmpeg 已经可用，无需重复安装。
        echo 路径: %BINDIR%ffmpeg.exe
        pause
        exit /b 0
    )
    echo 检测到 bin\ffmpeg.exe 但无法运行（缺运行时），将下载自包含版本覆盖。
)

echo.
echo   正在下载 ffmpeg （约 90MB，取决于网速）...
echo   来源: %URL%
echo.

REM 优先用 PowerShell 的多线程下载 API，通常比单线程快不少
powershell -NoProfile -Command ^
  "$p='%TMPZ%'; $ProgressPreference='SilentlyContinue';" ^
  "try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "(New-Object Net.WebClient).DownloadFile('%URL%',$p); Write-Host 'OK' }" ^
  "catch { Write-Host ('ERR:'+$_.Exception.Message); exit 1 }"

if errorlevel 1 goto fallback

if exist "%TMPZ%" goto unpack

:fallback
echo.
echo   PowerShell 下载失败，改用 curl ...
curl -L -o "%TMPZ%" "%URL%"
if errorlevel 1 goto failed

:unpack
echo.
echo   下载完成，正在解压 ...
powershell -NoProfile -Command ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$z=[System.IO.Compression.ZipFile]::OpenRead('%TMPZ%');" ^
  "$e=$z.Entries | Where-Object { $_.FullName -like '*/bin/ffmpeg.exe' } | " ^
  "Sort-Object Length -Descending | Select-Object -First 1;" ^
  "if(-not $e){ Write-Host 'NOEXE'; exit 1 }" ^
  "[System.IO.Compression.ZipFileExtensions]::ExtractToFile($e,'%BINDIR%ffmpeg.exe',$true);" ^
  "$z.Dispose(); Write-Host 'OK'"

if errorlevel 1 goto failed

del "%TMPZ%" 2>nul

if not exist "%BINDIR%ffmpeg.exe" goto failed

echo.
echo   安装完成！
echo.
"%BINDIR%ffmpeg.exe" -version | findstr "ffmpeg version"
echo.
echo   现在回到 KonkaCast 控制台，点右上角的「刷新」就能用屏幕镜像了。
echo.
pause
exit /b 0

:failed
echo.
echo   自动安装没成功。手动装也很简单：
echo   1. 浏览器打开 https://ffmpeg.org/download.html
echo   2. Windows 图标 -> Windows builds from gyan.dev
echo      或直接下: %URL%
echo   3. 解压，把里面的 bin\ffmpeg.exe 复制到：
echo      %BINDIR%
echo.
pause
exit /b 1
