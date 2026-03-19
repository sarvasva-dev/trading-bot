@echo off
setlocal enabledelayedexpansion
title Market Intelligence Bot v7.0 - Production Launcher

echo ======================================================
echo    MARKET INTELLIGENCE BOT v7.0 - SMART LAUNCHER
echo ======================================================

:: Find Python
set PY_CMD=python
python --version >nul 2>&1
if !errorlevel! equ 0 goto found_py

py --version >nul 2>&1
if !errorlevel! equ 0 (
    set PY_CMD=py
    goto found_py
)

echo [ERROR] Python not found! Please install Python from python.org
pause
exit /b

:found_py
echo [SYSTEM] Using Python command: !PY_CMD!

:: 1. Check for Virtual Environment
if exist venv goto venv_exists
echo [SYSTEM] Virtual environment not found. Creating 'venv'...
!PY_CMD! -m venv venv
if !errorlevel! neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b
)
echo [SYSTEM] venv created successfully.

:venv_exists
:: 2. Check for Pinned Dependencies
if not exist venv\Scripts\python.exe (
    echo [ERROR] venv\Scripts\python.exe not found. Re-creating venv...
    rd /s /q venv
    !PY_CMD! -m venv venv
)

echo [SYSTEM] Verifying environment modules...
venv\Scripts\python -c "import openai" >nul 2>&1
if !errorlevel! equ 0 goto deps_ok

echo [SYSTEM] Dependencies missing. Starting installation...
echo [INFO] Installing required packages. Please wait...

venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -r requirements.txt

if !errorlevel! neq 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b
)
echo [SUCCESS] Environment ready.

:deps_ok
:: 3. Database Migration Check
echo [SYSTEM] Ensuring Database schema is v7.0 compatible...
if exist migrate_v7.py venv\Scripts\python migrate_v7.py

:: 4. Start 24/7 Watchdog Loop
echo [SYSTEM] Starting Self-Restarting Watchdog...
echo [INFO] Close this window to stop the bot.
echo.

:monitor_loop
if not exist watchdog_service.py (
    echo [ERROR] watchdog_service.py missing!
    pause
    exit /b
)
venv\Scripts\python watchdog_service.py
echo [WARNING] Watchdog service stopped. Restarting in 10 seconds...
timeout /t 10
goto monitor_loop
