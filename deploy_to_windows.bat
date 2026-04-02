@echo off
REM Bulkbeat TV v1.0 - Windows Deployment Script
REM Usage: deploy_to_windows.bat

setlocal enabledelayedexpansion

set PROJECT_DIR=%cd%
set VENV_DIR=%PROJECT_DIR%\.venv
set LOG_DIR=%PROJECT_DIR%\logs

echo.
echo ==========================================
echo Bulkbeat TV Windows Deployment
echo ==========================================
echo.

REM 1. Check Python
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found or not in PATH
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo   ^x27 Python %PYTHON_VER% found
echo.

REM 2. Create virtualenv if missing
echo [2/6] Setting up Python virtualenv...
if not exist "%VENV_DIR%" (
    echo   Creating virtualenv...
    python -m venv "%VENV_DIR%"
    echo   ^x27 Virtualenv created
) else (
    echo   ^x27 Virtualenv already exists
)
echo.

REM 3. Install dependencies
echo [3/6] Installing dependencies...
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
pip install apscheduler >nul 2>&1
echo   ^x27 Dependencies installed
echo.

REM 4. Run migration
echo [4/6] Running database migration...
python migrate_v7.py
echo.

REM 5. Verify health
echo [5/6] Running health checks...
python -m nse_monitor.main --health
echo.

REM 6. Instructions
echo [6/6] Deployment preparation complete
echo.
echo ==========================================
echo ^✓ DEPLOYMENT READY
echo ==========================================
echo.
echo You can now run the bot with:
echo   - Windows (foreground): run.bat
echo   - Windows (watchdog): run_all.bat
echo   - Linux/VPS: bash run_all.sh
echo.
echo For systemd (Linux), use: systemctl start nsebot
echo.
echo Monitor logs: tail -f logs/app.log
echo.
pause
