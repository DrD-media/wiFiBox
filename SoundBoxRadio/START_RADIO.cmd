@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
title SoundBoxRadio
set PYTHONHOME=
set PYTHONPATH=
set PYTHONIOENCODING=utf-8
if not exist "runtime\python\python.exe" (
  echo Не найден встроенный Python: runtime\python\python.exe
  pause
  exit /b 1
)
"%~dp0runtime\python\python.exe" -I -u "%~dp0launch.py" %*
if errorlevel 1 pause
