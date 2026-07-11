@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo AMS Dashboard - Code Check
echo ========================================
echo.

set "PY_CMD=py -3.12"
%PY_CMD% --version >nul 2>nul
if errorlevel 1 set "PY_CMD=python"

echo [1/4] Python runtime:
%PY_CMD% --version
if errorlevel 1 goto fail

echo.
echo [2/4] Python syntax check...
%PY_CMD% -m py_compile bridge.py app\runtime.py app\main.py app\config.py app\state.py app\worker_client.py app\ams_web.py app\data_parser.py app\energy.py app\database.py app\schedules.py app\control.py
if errorlevel 1 goto fail

echo.
echo [3/4] Node worker syntax check...
vendor\node\node.exe --check worker.js
if errorlevel 1 goto fail

echo.
echo [4/5] Node map JSON check...
%PY_CMD% -c "import json; data=json.load(open('nodes.json', encoding='utf-8-sig')); print('remotes:', ', '.join(data.get('remotes', {}).keys()))"
if errorlevel 1 goto fail

echo.
echo [5/5] FastAPI import check...
%PY_CMD% -c "import bridge; print('routes:', len(bridge.app.routes))"
if errorlevel 1 goto fail

echo.
echo [extra] EXE launcher import check...
%PY_CMD% -c "import ams_dashboard_launcher; print('launcher import: ok')"
if errorlevel 1 goto fail

echo.
echo All checks passed.
pause
exit /b 0

:fail
echo.
echo Check failed. Read the message above.
pause
exit /b 1

