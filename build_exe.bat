@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Build EXE
echo ========================================
echo.

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

echo [1/3] Installing build packages...
%PY_CMD% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail

echo.
echo [2/3] Building EXE...
%PY_CMD% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --name AMS_Dashboard ^
  --add-data "dashboard.html;." ^
  --add-data "config.json;." ^
  --add-data "nodes.json;." ^
  --add-data "schedules.json;." ^
  --add-data "worker.js;." ^
  --add-data "node_modules;node_modules" ^
  --add-data "vendor;vendor" ^
  --add-data "assets;assets" ^
  --collect-all apscheduler ^
  --collect-all uvicorn ^
  --collect-all fastapi ^
  --collect-all pydantic ^
  ams_dashboard_launcher.py
if errorlevel 1 goto fail

echo.
echo [3/3] Build complete.
echo EXE: %CD%\dist\AMS_Dashboard.exe
pause
exit /b 0

:fail
echo.
echo Build failed. Check the message above.
pause
exit /b 1

