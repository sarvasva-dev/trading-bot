@echo off
setlocal
:: Ensure we are in the directory where the batch file is
cd /d "%~dp0"

:: If the batch file is inside nse_monitor, go to the parent directory
if exist "main.py" (
    cd ..
)

echo [1/3] Checking environment...
if not exist "nse_monitor\.env" (
    echo WARNING: .env file not found in nse_monitor folder!
    pause
    exit /b
)

echo [2/3] Installing/Updating requirements...
pip install -r nse_monitor\requirements.txt
if %ERRORLEVEL% neq 0 (
    echo Failed to install requirements.
    pause
    exit /b
)

echo [3/3] Starting NSE Announcements Monitor...
echo Press Ctrl+C to stop the monitor.
:: Run as a module from the root
python -m nse_monitor.main

pause
