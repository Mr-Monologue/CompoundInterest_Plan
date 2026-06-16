@echo off
chcp 65001 >nul
title Hermes Watcher — CompoundInterestPlan

:: .bat 所在目录就是项目根目录
cd /d "%~dp0"

echo ============================================================
echo  Hermes Watcher — 启动脚本
echo  工作目录: %CD%
echo ============================================================

:: 1. 激活虚拟环境
if exist ".venv\Scripts\python.exe" (
    echo [*] 使用虚拟环境 .venv
    set PYTHON=.venv\Scripts\python.exe
) else (
    echo [!] 未找到 .venv\Scripts\python.exe，使用系统 python
    set PYTHON=python
)

echo [*] Python: %PYTHON%

:: 2. 检查 Python 和核心模块
%PYTHON% -c "print('ok')" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [✗] Python 不可用，请检查环境。
    pause
    exit /b 1
)

:: 3. 快速检查 FastAPI 端口（用 Python 代替 curl）
%PYTHON% -c "
import socket; s=socket.socket(); s.settimeout(1)
r=s.connect_ex(('127.0.0.1',8701)); s.close(); exit(r)
" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [*] FastAPI 未运行，正在启动...
    start "CIP-API" %PYTHON% -m src.app.api --port 8701
    echo [*] 等待 3 秒...
    timeout /t 3 /nobreak >nul
) else (
    echo [✓] FastAPI 已在运行 (port 8701)
)

:: 4. 启动 Watcher（在同一窗口运行，不闪退）
echo.
echo [*] 启动 Hermes Watcher...
echo ============================================================
echo.
echo   按 Ctrl+C 停止 Watcher
echo.
echo ============================================================
echo.

%PYTHON% scripts\hermes_watcher.py 2>&1

:: 如果 Watcher 异常退出，显示错误并暂停
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [✗] Watcher 异常退出，错误码: %ERRORLEVEL%
    echo [✗] 请检查是否安装了所需的依赖，或手动运行诊断：
    echo     %PYTHON% scripts\hermes_watcher.py
)
pause
