@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Start Server
echo ========================================
echo.
echo Dashboard will open automatically.
echo LAN View uses the server_port value in config.json.
echo.

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

%PY_CMD% ams_dashboard_launcher.py

echo.
echo Server stopped.
pause

