# Bulkbeat TV v20.0 — VPS Deployment Guide (Ubuntu 22.04 LTS)

This guide details the procedure for deploying or upgrading the **Bulkbeat TV** institutional intelligence engine on a resource-constrained (1GB RAM) Linux VPS.

## 🏛️ Pre-Deployment Checklist
- [ ] SSH access to the target server.
- [ ] Prepared `.env` file with latest API keys (Sarvam, Telegram).
- [ ] Verified database snapshot (mandatory before upgrades).

---

## 1. System Preparation & Cleanup

Before installation, ensure the environment is clean and dependencies are met.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tesseract-ocr -y
```

### Stop Existing Services
```bash
sudo systemctl stop nsebot 2>/dev/null || true
pkill -f admin_bot.py 2>/dev/null || true
```

---

## 2. Code Deployment & Environment

```bash
git clone <repository_url>
cd nse2

# Initialize Virtual Environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Database Migration (v20.0 Institutional Shield)
```bash
# This step ensures the default Threshold 8 and re-branding are applied
python migrate_v7.py

# Perform a health check to verify AI and Telegram availability
python -m nse_monitor.main --health
```

---

## 3. Systemd Intelligence Engine Configuration

Create or update `/etc/systemd/system/nsebot.service`:

```ini
[Unit]
Description=Bulkbeat TV v20.0 Institutional Intelligence Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/nse2
EnvironmentFile=/root/nse2/.env
ExecStart=/root/nse2/venv/bin/python -m nse_monitor.main
Environment="PYTHONUNBUFFERED=1"
Restart=always
RestartSec=10
StandardOutput=append:/root/nse2/nse_monitor/logs/systemd.log
StandardError=append:/root/nse2/nse_monitor/logs/systemd.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable nsebot
sudo systemctl start nsebot
```

---

## 4. Admin Control Panel Initialization

The Admin Bot must be started as a persistent background process to enable real-time synchronization.

```bash
# Definitive Restart & Background Initialization
nohup python admin_bot.py > admin_bot.log 2>&1 &
```

---

## 5. Operations & Verification

### Audit Logs
```bash
# Stream the intelligence cycle
tail -f nse_monitor/logs/service.log

# Stream systemd outputs
journalctl -u nsebot -f
```

### Expected Initialization Output:
```
================================================
  Bulkbeat TV — The Pulse of Institutional Money
  Market Intelligence Engine v20.0 ONLINE
================================================
>>> Intelligence Cycle Started | Threshold=8 | Media=ACTIVE
```

---

## 🏗️ 1GB RAM Optimization Notes

- **Target RAM Usage**: 200–400 MB.
- **Memory Recycling**: The system performs an automated memory flush (`os._exit(0)`) every Sunday at 02:00 IST to prevent accumulated leak buildup.
- **OCR Throttling**: PDF extraction is performed serially to avoid CPU/RAM spikes.

---

## 🗓️ Intelligence Schedule (IST)

| Job | Time | Frequency |
|-----|------|-----------|
| Intelligence Cycle | Every 3 min | Continuous |
| Payment Gateway Check | Every 5 min | Continuous |
| **Morning Signal Report**| **08:30** | Mon-Fri |
| **Institutional Billing** | **16:00** | Mon-Fri |
| System Maintenance | 00:01 | Daily |
| Weekly Memory Flush | Sun 02:00 | Weekly |
| Market Holiday Sync | Sun 03:00 | Weekly |

---
*Developed by Bulkbeat TV Institutional Group.*
