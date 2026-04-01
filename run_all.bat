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

:: 1. Resolve Virtual Environment (.venv preferred, fallback to venv)
set VENV_DIR=.venv
if exist .venv\Scripts\python.exe goto venv_ready

if exist venv\Scripts\python.exe (
    set VENV_DIR=venv
    goto venv_ready
)

echo [SYSTEM] Virtual environment not found. Creating '.venv'...
!PY_CMD! -m venv .venv
if !errorlevel! neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b
)
set VENV_DIR=.venv
echo [SYSTEM] .venv created successfully.

:venv_ready
set PYTHON_EXE=!VENV_DIR!\Scripts\python.exe
if not exist !PYTHON_EXE! (
    echo [ERROR] !PYTHON_EXE! not found.
    pause
    exit /b
)

echo [SYSTEM] Using virtual environment: !VENV_DIR!

:: 2. Check for Required Dependencies
echo [SYSTEM] Verifying environment modules...
!PYTHON_EXE! -c "import aiohttp, apscheduler, pytz, dotenv" >nul 2>&1
if !errorlevel! equ 0 goto deps_ok

echo [SYSTEM] Dependencies missing. Starting installation...
echo [INFO] Installing required packages. Please wait...

!PYTHON_EXE! -m pip install --upgrade pip
!PYTHON_EXE! -m pip install -r requirements.txt
!PYTHON_EXE! -m pip install apscheduler

if !errorlevel! neq 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b
)
echo [SUCCESS] Environment ready.

:deps_ok
:: 3. Database Migration Check
echo [SYSTEM] Ensuring Database schema is v7.0 compatible...
if exist migrate_v7.py !PYTHON_EXE! migrate_v7.py

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
!PYTHON_EXE! watchdog_service.py
echo [WARNING] Watchdog service stopped. Restarting in 10 seconds...
timeout /t 10
goto monitor_loop
