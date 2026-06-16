@echo off
title Hermes Watcher

cd /d "%~dp0"

echo ============================================================
echo  Hermes Watcher - Startup
echo  WORKDIR: %CD%
echo ============================================================

:: 1. Find Python
if exist ".venv\Scripts\python.exe" (
    echo [*] Using .venv\Scripts\python.exe
    set "PY=.venv\Scripts\python.exe"
) else (
    echo [!] .venv not found, using system python
    set "PY=python"
)

:: 2. Check Python works
%PY% -c "print('OK')" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] Python not available
    pause
    exit /b 1
)

:: 3. Check if API is running on port 8701
%PY% -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8701)); s.close(); exit(r)" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [*] Starting FastAPI on port 8701...
    start "CIP-API" %PY% -m src.app.api --port 8701
    echo [*] Waiting 3 seconds...
    timeout /t 3 /nobreak >nul
) else (
    echo [OK] FastAPI already running
)

:: 4. Start Watcher
echo.
echo [*] Starting Hermes Watcher...
echo     Press Ctrl+C to stop
echo ============================================================
echo.

%PY% scripts\hermes_watcher.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [X] Watcher exited with code: %ERRORLEVEL%
    echo [X] Try running manually:
    echo     %PY% scripts\hermes_watcher.py
)
pause
