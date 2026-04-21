# Bulkbeat TV — Deployment Quick Reference

This document provides the authoritative installation and operational commands for the **Bulkbeat TV v20.0** institutional intelligence engine.

---

## 🚀 1. Installation

### Environment Preparation
```bash
# Update system and install dependencies
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tesseract-ocr -y

# Clone and initialize
git clone <repository_url>
cd nse2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Database Initialization
```bash
# Run the migration to ensure Threshold 8 and institutional settings
python migrate_v7.py
```

---

## 🛠️ 2. Operational Governance

### The Definitive Restart Command ("The Brahmastra")
Use this command to ensure all stale processes are killed and the system starts fresh with the latest code:
```bash
git pull origin main && pkill -f admin_bot.py && sudo systemctl restart nsebot && nohup python admin_bot.py > admin_bot.log 2>&1 &
```

### Service Management
```bash
# Check Intelligence Engine status
sudo systemctl status nsebot

# Audit system logs
tail -f nse_monitor/logs/service.log
```

---

## 🏗️ 3. Troubleshooting Process Orphans

If signals appear inconsistent or the Admin Panel does not sync instantly:
1. **Kill all active python processes**: `pkill -f python3`
2. **Execute the 'Definitive Restart'**: (See section 2 above).
3. **Verify Admin Bot**: Check `admin_bot.log` for any startup errors.

---

## 📊 4. System File Paths

- **Core Database**: `nse_monitor/data/processed_announcements.db`
- **Daily Backups**: `nse_monitor/data/backups/`
- **System Config**: `nse_monitor/config.py`
- **User Alerts**: `nse_monitor/telegram_bot.py`
- **Admin Dashboard**: `admin_bot.py`

---
*© 2026 Bulkbeat TV Institutional Group.*
