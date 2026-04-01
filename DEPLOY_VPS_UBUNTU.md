# Market Pulse v1.0 — VPS Deployment (Ubuntu 22.04, 1GB RAM)

## Pre-Deployment Checklist
- [ ] SSH access to VPS ready
- [ ] `.env` file with all tokens prepared locally
- [ ] Backup of current database (if upgrading)
- [ ] Admin chat ID noted

---

## Step 1: SSH into VPS and Navigate

```bash
ssh root@<VPS_IP>
cd /root/nse2
# Check if old version is running
ps aux | grep nse_monitor
```

**If running:** `systemctl stop nsebot` (if using systemd) or kill watchdog process

---

## Step 2: Pull Latest Code (Git or Manual)

### Option A: Via Git
```bash
git pull origin main
```

### Option B: Manual (If no git)
SCP/Upload the updated files to VPS:
```bash
scp -r ./* root@<VPS_IP>:/root/nse2/
```

---

## Step 3: Quick Validation Script

```bash
cd /root/nse2

# 1. Check Python version
python3 --version  # Should be 3.8+

# 2. Backup current DB (if exists)
[ -f nse_monitor/data/processed_announcements.db ] && cp nse_monitor/data/processed_announcements.db nse_monitor/data/processed_announcements.db.backup

# 3. Create/activate .venv
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies (with apscheduler fix)
pip install --upgrade pip
pip install -r requirements.txt
pip install apscheduler  # New explicit dependency

# 5. Run migration
python migrate_v7.py

# 6. Health check
python -m nse_monitor.main --health
```

---

## Step 4: Update Systemd Service

Edit `/etc/systemd/system/nsebot.service`:

```ini
[Unit]
Description=Market Pulse v1.0 Intelligence Engine
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/nse2
EnvironmentFile=/root/nse2/.env
ExecStart=/root/nse2/.venv/bin/python -m nse_monitor.main
Environment="PYTHONUNBUFFERED=1"

# Self-healing
Restart=always
RestartSec=5
StandardOutput=append:/root/nse2/logs/systemd.log
StandardError=append:/root/nse2/logs/systemd.log

[Install]
WantedBy=multi-user.target
```

Then restart:
```bash
systemctl daemon-reload
systemctl enable nsebot
systemctl start nsebot
```

---

## Step 5: Verify it Works

```bash
# Check logs
tail -f /root/nse2/logs/app.log

# Verify scheduler is running (should show "Pre-market report" job)
journalctl -u nsebot -f
```

Expected output around 08:30 IST:
```
INFO - Scheduler configured: 08:30 Reports | 00:01 Maintenance | 3-Min Polling.
INFO - Pre-market report already sent for 2026-04-01. Skipping duplicate.
```

---

## Step 6: Admin Access Fix

**Problem:** Admin couldn't grant access after login.
**Root Cause:** `is_admin_session_valid()` method was missing.
**Fix:** Database method restored in v1.0.1+

To test:
```bash
# Send /login <password> in Telegram to bot
# Then test /pulse command - should show system status
```

---

## Rollback Plan (If Issues)

```bash
systemctl stop nsebot

# Restore backup
cp nse_monitor/data/processed_announcements.db.backup nse_monitor/data/processed_announcements.db

# Revert to last git commit
git reset --hard HEAD~1

# Restart
systemctl start nsebot
```

---

## 1GB RAM Performance Notes

- **Expected Memory:** 200-400MB (Python + DB + async tasks)
- **Swap Recommended:** 512MB (`free -h` to check)
- **Monitor:** `watch -n 2 free -h`

If hitting swap:
```bash
# Reduce log retention
find /root/nse2/logs -name "*.log" -mtime +30 -delete
```

---

## Critical Timings

| Job | Time (IST) | Frequency |
|-----|-----------|-----------|
| Pre-Market Report | **08:30** | Mon-Fri |
| 3-Min Intel Cycle | Every 3 min | All-day |
| Daily Maintenance | 00:01 | Daily |
| Post-Market Billing | 16:00 | Mon-Fri |
| Holiday Sync | Sun 03:00 | Weekly |

---

## Support Log Format

If issues, attach:
```bash
# Copy these to support
tail -500 /root/nse2/logs/app.log > /root/nse2/logs/support_dump.txt
ps aux | grep python > /tmp/process_state.txt
free -h > /tmp/memory_state.txt
df -h > /tmp/disk_state.txt
```
