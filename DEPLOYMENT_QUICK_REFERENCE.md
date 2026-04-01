# Quick Deployment Reference - Market Pulse Bot

## 🚀 VPS Ubuntu 22.04 (1GB RAM) - Fast Track

### Pre-Flight Checks
```bash
ssh root@YOUR_VPS_IP
apt update && apt install -y python3-pip python3-venv git
cd /root/nse2
```

### Automated Deployment (Recommended)
```bash
bash deploy_to_ubuntu.sh
```

**What it does:**
- ✓ Stops existing service
- ✓ Backs up database
- ✓ Creates virtualenv
- ✓ Installs dependencies
- ✓ Runs migration
- ✓ Verifies health
- ✓ Starts systemd service

**Time:** ~5-7 minutes (depending on pip)

---

## 🖥️ Windows Local Machine - Fast Track

```cmd
cd C:\path\to\nse2
deploy_to_windows.bat
```

**What it does:**
- ✓ Creates virtualenv
- ✓ Installs dependencies
- ✓ Runs migration
- ✓ Runs health checks
- ✓ Shows run instructions

**Time:** ~3-5 minutes

---

## 🔧 Manual Deployment (If Script Fails)

### Step 1: Setup
```bash
python3 -m venv /root/nse2/.venv
source /root/nse2/.venv/bin/activate
cd /root/nse2
```

### Step 2: Install
```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install apscheduler
```

### Step 3: Migrate
```bash
python migrate_v7.py
```

### Step 4: Health Check
```bash
python -m nse_monitor.main --health
```

### Step 5: Start Service
```bash
systemctl daemon-reload
systemctl start nsebot
systemctl status nsebot
```

### Step 6: Monitor
```bash
tail -f /root/nse2/logs/app.log
```

**Expected output:**
```
Market Pulse Scheduler configured with 7 jobs
Scheduler running (IST timezone)
Listening for Telegram updates...
```

---

## ⚡ Critical Timings (IST / GMT+5:30)

| Time | Job | Status |
|------|-----|--------|
| 08:30 | Pre-Market Report | ✓ Guaranteed (catch-up logic) |
| Every 3min | Data Cycle | ✓ Continuous |
| Every 5min | Payment Check | ✓ Continuous |
| 16:00 | Daily Billing | ✓ Once/day |
| 00:01 | Maintenance | ✓ Once/day |
| Sun 02:00 | Memory Flush | ✓ Weekly |
| Sun 03:00 | Holiday Sync | ✓ Weekly |

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| "ModuleNotFoundError: apscheduler" | `pip install apscheduler` |
| "Admin access denied" | Verified ✓ Fixed in code |
| "Garbled Telegram messages" | Verified ✓ Fixed in code |
| Service won't start | Check: `journalctl -u nsebot -n 50` |
| Health check fails | Verify `.env` has TELEGRAM_BOT_TOKEN, CLAUDE_API_KEY |
| Memory near ceiling (1GB RAM) | Monitor: `watch -n 2 'free -h'` |

---

## 📊 Resource Monitoring (VPS)

```bash
# CPU & Memory
top -b -n 1 | head -20

# Specific to nsebot
ps aux | grep python

# Disk & Swap
df -h
free -h

# Service logs
journalctl -u nsebot -f
tail -f /root/nse2/logs/app.log
```

---

## ✅ Verification Checklist

After deployment:

- [ ] Service is running: `systemctl is-active nsebot`
- [ ] Health check passes: `python -m nse_monitor.main --health`
- [ ] Logs show "Scheduler configured": `tail /root/nse2/logs/app.log`
- [ ] Telegram bot responds to `/start` (in admin bot)
- [ ] Admin access works: `/login <password>` → `/grant` command available
- [ ] Pre-market report scheduled for tomorrow 08:30 IST

---

## 🔄 Rollback (If Issues)

### Restore Database Backup
```bash
cp /root/nse2/nse_monitor/data/backups/db_backup_YYYYMMDD_HHMMSS.db \
   /root/nse2/nse_monitor/data/processed_announcements.db
```

### Stop Service
```bash
systemctl stop nsebot
```

### Revert Code
```bash
cd /root/nse2
git checkout HEAD -- .
```

### Restart
```bash
systemctl start nsebot
```

---

## 📞 Support Quick Links

- **Logs:** `tail -f /root/nse2/logs/app.log`
- **Config:** `cat /root/nse2/.env`
- **Health:** `python -m nse_monitor.main --health`
- **Status:** `systemctl status nsebot`
- **Database:** `/root/nse2/nse_monitor/data/processed_announcements.db`

---

**Last Updated:** Post Admin-Fix (v1.0 stable)  
**Target:** Ubuntu 22.04 + Windows  
**Tested:** ✓ Health checks pass, ✓ Admin access working, ✓ Encoding fixed
