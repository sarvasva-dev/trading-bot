# Deployment Quick Reference — Bulkbeat TV v2.0

## 🚀 VPS Ubuntu 22.04 — Fast Track

```bash
ssh root@YOUR_VPS_IP
cd /root/nse2
bash deploy_to_ubuntu.sh
```

**What it does:** stops service → backs up DB → creates venv → installs deps → migrates → health check → starts systemd

---

## 🖥️ Windows — Fast Track

```cmd
cd C:\path\to\nse2
deploy_to_windows.bat
```

---

## 🔧 Manual Steps

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python migrate_v7.py
python -m nse_monitor.main --health
systemctl daemon-reload && systemctl start nsebot
```

---

## ⚡ Scheduler (IST)

| Time | Job |
|------|-----|
| Every 3 min | Intelligence Cycle |
| Every 5 min | Payment Check |
| 08:30 Mon-Fri | Pre-Market Report |
| 16:00 Mon-Fri | EOD Billing |
| 00:01 Daily | Maintenance + Backup |
| Sun 02:00 | Memory Flush |
| Sun 03:00 | Holiday Sync |

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Service won't start | `journalctl -u nsebot -n 50` |
| Health check fails | Verify `.env`: TELEGRAM_BOT_TOKEN, SARVAM_API_KEY |
| No alerts firing | Check `ALERT_POLICY_MODE=ULTRA_STRICT_8PLUS` + source whitelist |
| Memory near 1GB | Weekly flush at Sun 02:00 auto-handles; check `free -h` |

---

## ✅ Post-Deploy Verification

```bash
systemctl is-active nsebot
python -m nse_monitor.main --health
tail -f /root/nse2/nse_monitor/logs/app.log
```

Expected log:
```
Bulkbeat TV v2.0 - ASYNC OS BOOT
Warmup complete. System entering high-trust monitoring mode.
```

- Admin bot: `/login <password>` → `/pulse`
- Next morning report: tomorrow 08:30 IST (if trading day)

---

## 🔄 Rollback

```bash
systemctl stop nsebot
cp nse_monitor/data/processed_announcements.db.backup \
   nse_monitor/data/processed_announcements.db
git checkout HEAD -- .
systemctl start nsebot
```

---

## 📞 Quick Links

| What | Command |
|------|---------|
| Logs | `tail -f /root/nse2/nse_monitor/logs/app.log` |
| Health | `python -m nse_monitor.main --health` |
| Status | `systemctl status nsebot` |
| DB | `nse_monitor/data/processed_announcements.db` |
