@echo off
echo ======================================================
echo    MARKET INTELLIGENCE BOT v7.0 - MANUAL TEST
echo ======================================================
echo [SYSTEM] Triggering one-time Intelligence Cycle...
echo [INFO] TEST_MARKET_OPEN is active in config.py.
echo.

venv\Scripts\python -m nse_monitor.main

echo.
echo ======================================================
echo [SUCCESS] Manual Cycle Complete.
pause
