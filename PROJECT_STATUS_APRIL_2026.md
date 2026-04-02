# 🎯 Bulkbeat TV v2.0 — Project Status

## ✅ OVERALL STATUS: PRODUCTION READY

---

## 📊 Architecture Summary

| Component | Details |
|-----------|---------|
| **Runtime** | Python 3.8+, fully async (`asyncio`) |
| **AI Engine** | Sarvam 30B (`sarvam-30b`) |
| **Alert Policy** | `ULTRA_STRICT_8PLUS` (score ≥ 8, whitelisted sources) |
| **Data Sources** | 5 (NSE, NSE SME, Bulk Deals, ET, MC) |
| **Database** | SQLite WAL, 30s timeout, auto-backup |
| **Scheduler** | APScheduler AsyncIO, 7 jobs, IST timezone |
| **Memory** | 200–400 MB (1GB VPS comfortable) |

---

## 🔧 Key Fixes & Features (v2.0)

✅ **Fully Async Core** — ThreadPool removed, pure `asyncio.gather()` pipeline  
✅ **5-Source Ingestion** — NSE, NSE SME, Bulk Deals, ET, MC  
✅ **SHA-256 Deduplication** — Content hash before every DB insert  
✅ **Ultra-Strict Policy** — Score ≥ 8 + source whitelist + cooldown + cap  
✅ **Smart Money Analysis** — Auto-triggered for score ≥ 7  
✅ **Impact Tracker** — Post-alert price movement tracking  
✅ **Nudge Manager** — Inactive subscriber re-engagement  
✅ **Single-Instance PID Lock** — No duplicate processes  
✅ **Startup Warmup** — 3 forced cycles on boot  
✅ **Startup Catch-up Report** — Missed 08:30 report auto-dispatched on restart  
✅ **Garbled Message Fix** — Mojibake sanitizer on all Telegram send paths  
✅ **Admin Access** — `is_admin_session_valid()` restored  
✅ **Holiday Calendar** — Auto-sync Sun 03:00 IST  

---

## 🎯 Scheduler Jobs (IST)

| Time | Job | Frequency |
|------|-----|-----------|
| Every 3 min | Intelligence Cycle | Continuous |
| Every 5 min | Payment Check | Continuous |
| **08:30** | Pre-Market Report | Mon-Fri |
| **16:00** | EOD Billing | Mon-Fri |
| **00:01** | Daily Maintenance + Backup | Daily |
| Sun **02:00** | Memory Flush (`os._exit(0)`) | Weekly |
| Sun **03:00** | Holiday Calendar Sync | Weekly |

---

## 📋 Pre-Production Checklist

- [ ] `.env` verified (TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, SARVAM_API_KEY)
- [ ] `python migrate_v7.py` run
- [ ] `python -m nse_monitor.main --health` passes
- [ ] Systemd service started: `systemctl start nsebot`
- [ ] Logs clean: `tail -f nse_monitor/logs/app.log`
- [ ] Admin bot `/login <password>` → `/pulse` works
- [ ] Morning report received at 08:30 IST next trading day
