# Bulkbeat TV v2.0 — VPS Deployment (Ubuntu 22.04, 1GB RAM)

## Pre-Deployment Checklist
- [ ] SSH access ready
- [ ] `.env` file prepared locally
- [ ] DB backup taken (if upgrading)

---

## Step 1: SSH & Stop Existing Service

```bash
ssh root@<VPS_IP>
systemctl stop nsebot 2>/dev/null || true
cd /root/nse2
```

---

## Step 2: Pull Latest Code

```bash
git pull origin main
# OR manual upload:
# scp -r ./* root@<VPS_IP>:/root/nse2/
```

---

## Step 3: Setup & Install

```bash
# Backup DB
[ -f nse_monitor/data/processed_announcements.db ] && \
  cp nse_monitor/data/processed_announcements.db nse_monitor/data/processed_announcements.db.backup

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Migrate DB schema
python migrate_v7.py

# Health check
python -m nse_monitor.main --health
```

---

## Step 4: Systemd Service

`/etc/systemd/system/nsebot.service`:

```ini
[Unit]
Description=Bulkbeat TV v2.0 Intelligence Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/nse2
EnvironmentFile=/root/nse2/.env
ExecStart=/root/nse2/.venv/bin/python -m nse_monitor.main
Environment="PYTHONUNBUFFERED=1"
Restart=always
RestartSec=5
StandardOutput=append:/root/nse2/nse_monitor/logs/systemd.log
StandardError=append:/root/nse2/nse_monitor/logs/systemd.log

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable nsebot
systemctl start nsebot
```

---

## Step 5: Verify

```bash
tail -f /root/nse2/nse_monitor/logs/app.log
journalctl -u nsebot -f
```

Expected on startup:
```
Bulkbeat TV v2.0 - ASYNC OS BOOT
System initialized. Async core online.
Scheduler configured: 08:30 Reports | 00:01 Maintenance | 3-Min Polling.
Warmup complete. System entering high-trust monitoring mode.
```

---

## Rollback

```bash
systemctl stop nsebot
cp nse_monitor/data/processed_announcements.db.backup nse_monitor/data/processed_announcements.db
git reset --hard HEAD~1
systemctl start nsebot
```

---

## 1GB RAM Notes

- Expected: 200–400 MB
- Monitor: `watch -n 2 free -h`
- Weekly `os._exit(0)` at Sun 02:00 IST auto-clears memory leak buildup

---

## Scheduler Reference (IST)

| Job | Time | Frequency |
|-----|------|-----------|
| Intelligence Cycle | Every 3 min | Continuous |
| Payment Check | Every 5 min | Continuous |
| Pre-Market Report | 08:30 | Mon-Fri |
| EOD Billing | 16:00 | Mon-Fri |
| Daily Maintenance | 00:01 | Daily |
| Memory Flush | Sun 02:00 | Weekly |
| Holiday Sync | Sun 03:00 | Weekly |
