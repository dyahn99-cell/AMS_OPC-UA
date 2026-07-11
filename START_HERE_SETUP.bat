@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Setup
echo ========================================
echo.

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

echo [1/2] Python runtime:
%PY_CMD% --version
if errorlevel 1 goto fail

echo.
echo [2/2] Installing Python packages...
%PY_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo.
echo Setup complete.
echo You can now run START_DASHBOARD.bat
pause
exit /b 0

:fail
echo.
echo Setup failed. Check Python 3.12 and pip installation.
pause
exit /b 1

