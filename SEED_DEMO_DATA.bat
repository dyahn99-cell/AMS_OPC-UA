@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Seed Demo History
echo ========================================
echo.
echo Generates realistic multi-day history for
echo DATA / ENERGY charts without live hardware.
echo.

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

%PY_CMD% --version
if errorlevel 1 goto fail

echo.
echo Seeding 14 days / 60s interval for AMS00 + AMS01...
echo Existing rows in the same range are replaced.
echo.

%PY_CMD% scripts\seed_demo_data.py --days 14 --interval-s 60 --remotes AMS00,AMS01 --replace-range
if errorlevel 1 goto fail

echo.
echo Demo data ready. Open DATA / ENERGY in the dashboard.
pause
exit /b 0

:fail
echo.
echo Seed failed. Read the message above.
pause
exit /b 1
