@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
set "RADIO_COM=%~1"
if "%RADIO_COM%"=="" set "RADIO_COM=auto"
"%~dp0runtime\python\python.exe" -I -X utf8 "%~dp0tools\firmware.py" --flash "%RADIO_COM%"
set "RADIO_RESULT=%errorlevel%"
pause
exit /b %RADIO_RESULT%
