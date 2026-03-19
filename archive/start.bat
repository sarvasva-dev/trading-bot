@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Validating Environment...
if not exist ".env" (
    echo [ERROR] .env file not found! Please create it from .env.example.
    pause
    exit /b
)

echo [2/3] Installing Intelligence System Dependencies...
echo This will be quick (Optimized Lightweight Mode)...
python -m pip install --upgrade pip
pip install -r requirements.txt

if %ERRORLEVEL% neq 0 (
    echo [ERROR] Dependency installation failed! 
    echo Check your internet connection or Python version.
    pause
    exit /b
)

echo [3/3] Launching Intelligence Engine v3.5 [Active Intelligence]...
echo --------------------------------------------------
echo Press Ctrl+C to stop the monitor.
:: Run from the parent directory to ensure absolute imports work
cd ..
python -m nse_monitor.main
pause
