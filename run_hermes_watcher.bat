@echo off
chcp 65001 >nul
title Hermes Watcher — CompoundInterestPlan

cd /d "%~dp0.."

echo ============================================================
echo  Hermes Watcher — 启动脚本
echo ============================================================

:: 1. 激活虚拟环境
if exist ".venv\Scripts\activate.bat" (
    echo [*] 激活虚拟环境 .venv
    call .venv\Scripts\activate.bat
) else (
    echo [!] 未找到 .venv，使用系统 Python
)

:: 2. 检查 FastAPI 是否已运行
curl -s http://127.0.0.1:8701/api/health >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] 启动 FastAPI 服务器 (port 8701)...
    start "CIP-API" cmd /c "python -m src.app.api --port 8701"
    echo [*] 等待 3 秒让 API 启动...
    timeout /t 3 /nobreak >nul
) else (
    echo [✓] FastAPI 已在运行
)

:: 3. 启动 Watcher
echo [*] 启动 Hermes Watcher...
python scripts\hermes_watcher.py

:: 4. Watcher 停止后
echo.
echo [!] Hermes Watcher 已退出。
pause
