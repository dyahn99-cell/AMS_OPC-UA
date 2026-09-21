@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Guarded Offline Check
echo ========================================
echo.

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

rem No app imports, bytecode writes, live config reads, or Node processes here.
rem Add --regressions-only to omit the separately reported stage-1 contracts.
%PY_CMD% scripts\check_offline.py %*
if errorlevel 1 goto fail

echo.
echo Selected offline checks passed. See NOT_RUN and safety scope above.
pause
exit /b 0

:fail
echo.
echo Offline check failed. Review regression, contract, and safety summaries separately.
pause
exit /b 1
