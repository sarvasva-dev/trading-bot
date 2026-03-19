@echo off
echo =========================================================
echo    Market Intelligence Bot V7.5 - Production Deploy
echo =========================================================
echo.

echo [1/3] Checking Virtual Environment...
IF NOT EXIST venv (
    echo Creating Python Virtual Environment (venv)...
    python -m venv venv
)

echo [2/3] Activating venv and Installing Dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt

echo [3/3] Checking Environment Configurations...
IF NOT EXIST .env (
    IF EXIST .env.example (
        echo Creating default .env file from .env.example...
        copy .env.example .env
        echo.
        echo ACTION REQUIRED: Please edit '.env' to add your LLM and Telegram tokens, then re-run this script!
        pause
        exit /b 1
    ) ELSE (
        echo ERROR: .env file is missing and .env.example was not found. Please create one.
        pause
        exit /b 1
    )
)

echo.
echo =========================================================
echo SUCCESS! Starting the Market Intelligence Bot...
echo =========================================================
echo Note: This window will stay open to show output if run directly.
echo To run entirely hidden, schedule this batch file via Task Scheduler.
echo.

title Market Intelligence Bot v7.5
python -m nse_monitor.main
pause
