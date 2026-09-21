@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Start Server
echo ========================================
echo.
echo Dashboard URL: http://127.0.0.1:8000
echo LAN View uses the server_port value in config.json.
echo.

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  echo Port 8000 is already in use by PID %%P.
  echo Open http://127.0.0.1:8000 instead of starting another server.
  echo Close this window, or stop PID %%P first if you really want a restart.
  pause
  exit /b 0
)

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

:run
%PY_CMD% ams_dashboard_launcher.py
set "SERVER_EXIT=%ERRORLEVEL%"
if "%SERVER_EXIT%"=="0" goto stopped

echo.
echo Server exited with code %SERVER_EXIT%. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto run

:stopped
echo.
echo Server stopped.
pause
