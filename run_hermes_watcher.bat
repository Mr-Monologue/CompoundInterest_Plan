@echo off
setlocal enabledelayedexpansion
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

:: 3. Check / start API (retry up to 5 times, 2 sec each)
set "API_OK=0"
for /L %%i in (1,1,5) do (
    if "!API_OK!"=="0" (
        %PY% -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',8701)); s.close(); exit(r)" 2>nul
        if !ERRORLEVEL! EQU 0 (
            set "API_OK=1"
        ) else (
            if %%i EQU 1 (
                echo [*] Starting FastAPI on port 8701...
                start "CIP-API" /D "%CD%" %PY% -m src.app.api --port 8701
            )
            echo [*] Waiting for API... (%%i/5)
            timeout /t 2 /nobreak >nul
        )
    )
)
if "!API_OK!"=="1" (
    echo [OK] FastAPI running on port 8701
) else (
    echo [!] API did not start. Watcher will retry later.
    echo     Check: %PY% -m src.app.api --port 8701
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
