#!/bin/bash
# run_all.sh
# Ubuntu/Linux launcher for Market Pulse v1.0

echo "======================================================"
echo "   MARKET PULSE v1.0 - LINUX LAUNCHER                 "
echo "======================================================"

# Check if python3-venv is installed
if ! dpkg -s python3-venv >/dev/null 2>&1; then
    echo "[SYSTEM] Installing python3-venv..."
    sudo apt-get update && sudo apt-get install -y python3-venv
fi

# 1. Check for Virtual Environment
if [ ! -d "venv" ]; then
    echo "[SYSTEM] Virtual environment not found. Creating 'venv'..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment."
        exit 1
    fi
    echo "[SYSTEM] venv created successfully."
fi

# 2. Check Dependencies
echo "[SYSTEM] Verifying environment modules..."
if ! venv/bin/python -c "import sarvamai" >/dev/null 2>&1; then
    echo "[SYSTEM] Dependencies missing. Starting installation..."
    venv/bin/python -m pip install --upgrade pip
    venv/bin/python -m pip install -r requirements.txt
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
    venv/bin/python -m nse_monitor.main
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo "[WATCHDOG] Engine triggered self-healing restart (Exit 0)."
    else
        echo "[ERROR] Engine crashed (Exit $exit_code). Restarting..."
    fi
    
    echo "Restarting in 5 seconds..."
    sleep 5
done
