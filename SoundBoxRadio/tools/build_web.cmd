@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0..\frontend"
"..\runtime\node\node.exe" "node_modules\vite\bin\vite.js" build
if errorlevel 1 pause
