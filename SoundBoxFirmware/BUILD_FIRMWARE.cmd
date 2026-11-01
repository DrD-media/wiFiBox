@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -I -X utf8 "%~dp0tools\firmware.py" --build
set "RADIO_RESULT=%errorlevel%"
pause
exit /b %RADIO_RESULT%
