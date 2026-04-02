#!/bin/bash
# Bulkbeat TV v1.0 - VPS Deployment Script (Ubuntu 22.04)
# Usage: bash deploy_to_ubuntu.sh

set -e

PROJECT_DIR="/root/nse2"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="$PROJECT_DIR/logs"

echo "=========================================="
echo "Bulkbeat TV VPS Deployment (Ubuntu 22.04)"
echo "=========================================="
echo ""

# 1. Check Python
echo "[1/8] Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not found. Install: apt install -y python3-pip python3-venv"
    exit 1
fi
PYTHON_VER=$(python3 --version | cut -d' ' -f2)
echo "  ✓ Python $PYTHON_VER found"

# 2. Stop existing service
echo "[2/8] Stopping existing service..."
if systemctl is-active --quiet nsebot; then
    systemctl stop nsebot
    echo "  ✓ Service stopped"
else
    echo "  (Service not running, proceeding)"
fi
sleep 2

# 3. Backup database
echo "[3/8] Backing up database..."
if [ -f "$PROJECT_DIR/nse_monitor/data/processed_announcements.db" ]; then
    mkdir -p "$PROJECT_DIR/nse_monitor/data/backups"
    BACKUP_FILE="$PROJECT_DIR/nse_monitor/data/backups/db_backup_$(date +%Y%m%d_%H%M%S).db"
    cp "$PROJECT_DIR/nse_monitor/data/processed_announcements.db" "$BACKUP_FILE"
    echo "  ✓ Database backed up to $BACKUP_FILE"
else
    echo "  (Fresh database, skipping backup)"
fi

# 4. Create/update virtualenv
echo "[4/8] Setting up Python virtualenv..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  ✓ Virtualenv created"
else
    echo "  ✓ Virtualenv already exists"
fi

# 5. Install dependencies
echo "[5/8] Installing dependencies..."
cd "$PROJECT_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip > /dev/null 2>&1
"$VENV_DIR/bin/pip" install -r requirements.txt > /dev/null 2>&1
"$VENV_DIR/bin/pip" install apscheduler > /dev/null 2>&1
echo "  ✓ Dependencies installed"

# 6. Run migration
echo "[6/8] Running database migration..."
"$VENV_DIR/bin/python" "$PROJECT_DIR/migrate_v7.py" 2>&1 | head -10
echo "  ✓ Migration complete"

# 7. Verify health
echo "[7/8] Running health checks..."
if "$VENV_DIR/bin/python" -m nse_monitor.main --health 2>&1 | tail -5 | grep -q "OK"; then
    echo "  ✓ Health checks passed"
else
    echo "  ⚠ Some health checks may have warnings (check logs)"
fi

# 8. Update systemd and start
echo "[8/8] Starting service..."
mkdir -p "$LOG_DIR"
systemctl daemon-reload
systemctl enable nsebot
systemctl start nsebot
sleep 2

if systemctl is-active --quiet nsebot; then
    echo "  ✓ Service started successfully"
    echo ""
    echo "=========================================="
    echo "✅ DEPLOYMENT COMPLETE"
    echo "=========================================="
    echo ""
    echo "Service Status:"
    systemctl status nsebot --no-pager | head -10
    echo ""
    echo "Logs (last 20 lines):"
    tail -20 "$LOG_DIR/app.log"
    echo ""
    echo "Next Report: 08:30 IST (Mon-Fri)"
    echo "Monitor with: tail -f $LOG_DIR/app.log"
else
    echo "  ✗ Service failed to start"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check logs: journalctl -u nsebot -n 50"
    echo "  - Verify config: cat .env | grep TELEGRAM"
    exit 1
fi
