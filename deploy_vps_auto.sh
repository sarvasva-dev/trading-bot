#!/bin/bash

# =================================================================
#  MARKET INTELLIGENCE BOT v7.5 - ONE-CLICK VPS INSTALLER (Ubuntu)
# =================================================================

set -e  # Exit strictly on error

echo "🚀 Starting Deployment for Market Intelligence Bot v7.5..."
echo "--------------------------------------------------------"

# 1. UPDATE SYSTEM
echo "[1/6] Updating System Packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git curl

# 2. CLONE REPO (Prompt for URL if not hardcoded)
echo "[2/6] Setting up Repository..."
REPO_DIR="$HOME/nse_bot"
if [ -d "$REPO_DIR" ]; then
    echo "Existing directory found. Pulling latest code..."
    cd "$REPO_DIR"
    git pull
else
    # REPLACE THIS URL WITH YOUR NEW REPO URL
    read -p "Enter your GIT REPO URL: " GIT_URL
    git clone "$GIT_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

# 3. PYTHON VIRTUAL ENVIRONMENT
echo "[3/6] Configuring Python Environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual Environment Created."
fi

# Install Dependencies
source venv/bin/activate
echo "Installing Python Libraries (Scanning requirements.txt)..."
# Combine all requirements files if separated
pip install --upgrade pip
if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi
if [ -f "nse_monitor/requirements.txt" ]; then pip install -r nse_monitor/requirements.txt; fi

# 4. ENVIRONMENT VARIABLES
echo "[4/6] Setting up Secrets..."
if [ ! -f ".env" ]; then
    echo "⚠️ .env file missing!"
    echo "Creating .env template... You MUST edit this later."
    cat <<EOT >> .env
# --- Market Bot Config ---
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_id_here
SARVAM_API_KEY=your_key_here
# --- Email Config ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
EOT
else
    echo ".env file already exists. Skipping."
fi

# 5. SYSTEMD SERVICE SETUP (Auto-Restart on Crash/Reboot)
echo "[5/6] Generating Systemd Service..."
SERVICE_PATH="/etc/systemd/system/nsebot.service"

# Dynamically write service file with correct user paths
sudo bash -c "cat > $SERVICE_PATH" <<EOT
[Unit]
Description=Market Intelligence Bot v7.5 (Live)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_DIR
# Using the python executable from venv
ExecStart=$REPO_DIR/venv/bin/python3 -m nse_monitor.main
# Environment
EnvironmentFile=$REPO_DIR/.env
# Crash Recovery
Restart=always
RestartSec=5
# Logging
StandardOutput=append:$REPO_DIR/logs/service.log
StandardError=append:$REPO_DIR/logs/service_error.log

[Install]
WantedBy=multi-user.target
EOT

# Reload Systemd
sudo systemctl daemon-reload
sudo systemctl enable nsebot

# 6. COMPLETION & INSTRUCTIONS
echo "--------------------------------------------------------"

# Make view_logs.sh executable
chmod +x view_logs.sh

# Start the service
echo "Starting nsebot service..."
sudo systemctl daemon-reload
sudo systemctl enable nsebot
sudo systemctl start nsebot

echo "✅ Installed & Started Successfully!"
echo "--------------------------------------------------------"
echo "👉 To view logs: ./view_logs.sh"
echo "👉 To stop bot: sudo systemctl stop nsebot"
echo "👉 To restart bot: sudo systemctl restart nsebot"
echo "--------------------------------------------------------"
echo "✅ DEPLOYMENT PREPARATION COMPLETE!"
echo "--------------------------------------------------------"
echo "NEXT STEPS:"
echo "1. Edit your secrets file:  nano $REPO_DIR/.env"
echo "2. Start the bot:           sudo systemctl start nsebot"
echo "3. Check logs:              tail -f $REPO_DIR/logs/app.log"
echo "--------------------------------------------------------"
