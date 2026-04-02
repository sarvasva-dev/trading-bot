#!/bin/bash
# run_all.sh
# Ubuntu/Linux launcher for Bulkbeat TV v1.0

echo "======================================================"
echo "   BULKBEAT TV v1.0 - LINUX LAUNCHER                 "
echo "======================================================"

# Check if python3-venv is installed
if ! dpkg -s python3-venv >/dev/null 2>&1; then
    echo "[SYSTEM] Installing python3-venv..."
    sudo apt-get update && sudo apt-get install -y python3-venv
fi

# 1. Resolve Virtual Environment (.venv preferred, fallback to venv)
VENV_DIR=".venv"
if [ -x ".venv/bin/python" ]; then
    VENV_DIR=".venv"
elif [ -x "venv/bin/python" ]; then
    VENV_DIR="venv"
else
    echo "[SYSTEM] Virtual environment not found. Creating '.venv'..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment."
        exit 1
    fi
    VENV_DIR=".venv"
    echo "[SYSTEM] .venv created successfully."
fi

PYTHON_EXE="$VENV_DIR/bin/python"
echo "[SYSTEM] Using virtual environment: $VENV_DIR"

# 2. Check Dependencies
echo "[SYSTEM] Verifying environment modules..."
if ! "$PYTHON_EXE" -c "import aiohttp, apscheduler, pytz, dotenv" >/dev/null 2>&1; then
    echo "[SYSTEM] Dependencies missing. Starting installation..."
    "$PYTHON_EXE" -m pip install --upgrade pip
    "$PYTHON_EXE" -m pip install -r requirements.txt
    "$PYTHON_EXE" -m pip install apscheduler
    if [ $? -ne 0 ]; then
        echo "[ERROR] Dependency installation failed."
        exit 1
    fi
    echo "[SUCCESS] Environment ready."
fi

# 3. Start 24/7 Watchdog Loop
echo "[SYSTEM] Starting Self-Restarting Engine (v1.0)..."
echo "[INFO] Press Ctrl+C to stop the bot."
echo ""

while true; do
    "$PYTHON_EXE" -m nse_monitor.main
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo "[WATCHDOG] Engine triggered self-healing restart (Exit 0)."
    else
        echo "[ERROR] Engine crashed (Exit $exit_code). Restarting..."
    fi
    
    echo "Restarting in 5 seconds..."
    sleep 5
done
