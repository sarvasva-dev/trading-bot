# Bulkbeat TV — Market Intelligence Engine
> NSE Institutional Intelligence Pipeline | v3.1 | Non-SEBI Research Tool

---

## ✅ WORKING — Core System

### Pipeline (Live on VPS)
| Component | File | Status |
|-----------|------|--------|
| NSE Corporate Filings Scraper | `sources/nse_source.py` | ✅ Live |
| NSE SME Filings Scraper | `sources/nse_sme_source.py` | ✅ Live |
| Economic Times Scraper | `sources/economic_times_source.py` | ✅ Live |
| Moneycontrol Scraper | `sources/moneycontrol_source.py` | ✅ Live |
| Sarvam 30B LLM Processor (22-Rule Prompt) | `llm_processor.py` | ✅ Live |
| SQLite Queue with WAL Mode | `database.py` | ✅ Live |
| PDF Enrichment (NSE filings) | `pdf_processor.py` | ✅ Live |
| Semantic Deduplication (headline hash) | `database.py` | ✅ Live |
| Market Hours Guard (09:15–15:30 IST) | `main.py` | ✅ Live |
| Live Alert Dispatch → Telegram | `telegram_bot.py` | ✅ Live |
| Off-Hours Queue → status=3 | `main.py` | ✅ Live |
| Morning Signal Dispatch (8:30 AM) | `scheduler.py` | ✅ Live |
| Stale Queue Pruner (market hours only) | `main.py` + `database.py` | ✅ v3.1 |
| Impact Tracker (post-alert price watch) | `impact_tracker.py` | ✅ Live |
| APScheduler (3-min cycle) | `scheduler.py` | ✅ Live |
| Trading Calendar (holiday awareness) | `trading_calendar.py` | ✅ Live |
| NSE Holiday Auto-Sync | `trading_calendar.py` | ✅ Live |
| Daily Auto Backup | `main.py` | ✅ Live |
| BotWatchdog (crash monitor) | `watchdog.py` | ✅ Live |

### User Telegram Bot — Commands
| Command | Function | Status |
|---------|----------|--------|
| `/start` | Welcome + Dashboard (if subscribed) | ✅ Working |
| `/plan` | Balance + expiry date | ✅ Working |
| `/hisab` | Daily billing audit log | ✅ Working |
| `/subscribe` | Plan selection menu | ✅ Working |
| `/sub_<amount>` | Razorpay payment link | ✅ Working |
| `/verify` | Manual payment verify | ✅ Working |
| `/support` | WhatsApp admin link | ✅ Working |
| `/status` (admin only) | NSE + AI + DB live check | ✅ Working |
| Rate limiting (5 req/min) | Brute-force protection | ✅ Working |
| Bcrypt admin login (`/login`) | Session auth | ✅ Working |

### Admin Bot — Controls
| Feature | Status |
|---------|--------|
| `/login <pass>` + Bcrypt verify | ✅ Working |
| Brute-force lockout (3 fails → 15 min block) | ✅ Working |
| Main Menu (buttons UI) | ✅ Working |
| System Status | ✅ Working |
| `/pulse` / `/health` — Uptime, RAM, Disk, DB size | ✅ Working |
| Bot Config → AI Threshold (4/6/8) | ✅ Working |
| Bot Config → Media Mute toggle | ✅ Working |
| User Audit — paginated list | ✅ Working |
| Manage User → Grant Days | ✅ Working |
| Manage User → Reset to 0 | ✅ Working |
| Manage User → Deactivate | ✅ Working |
| `/find <id/name>` — DB search | ✅ Working |
| `/grant <id> <days>` — manual CLI grant | ✅ Working |
| `/broadcast TITLE | MESSAGE` — all active users | ✅ Working |
| DB Rescue → VACUUM | ✅ Working |
| DB Rescue → Purge (30-day old news) | ✅ Working |
| DB Rescue → Sync NSE Holidays | ✅ Working |
| Global Hisab (daily/weekly billing audit) | ✅ Working |
| `/logout` — session clear | ✅ Working |
| Single-instance lock (`admin_bot.pid`) | ✅ Working |

### Payment System
| Feature | Status |
|---------|--------|
| Razorpay payment link generation | ✅ Working |
| Auto payment verification (webhook poll) | ✅ Working |
| Market-day billing (no deduction on holidays) | ✅ Working |
| 2 free trial days for new users | ✅ Working |
| Expiry nudge (1 day left → reminder) | ✅ Working |

---

## ⚠️ PRESENT BUT INACTIVE — Dead Code (DO NOT DELETE — May be used later)

| File | Class/Function | Reason Inactive |
|------|----------------|-----------------|
| `classifier.py` | `NewsClassifier` | Not imported anywhere in active pipeline. Pre-LLM era remnant. |
| `market_analyzer.py` | `MarketAnalyzer` | Imported in `main.py` line 31, instantiated line 141 (`self.analyzer`), but **never called** anywhere in codebase. |
| `clusterer.py` | `EventClusterer` | Not imported anywhere. Also auto-disables itself on 1GB RAM (`total_ram_gb < 1.5`). Requires `sentence-transformers` + `sklearn`. |
| `email_notifier.py` | `EmailNotifier` | Not imported anywhere. SMTP config (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`) not in `.env`. |
| `sources/bulk_deal_source.py` | `BulkDealSource` | Commented out in `main.py` line 36. Used only in `report_builder.py`. NSE Bulk Deal tracking was intentionally removed. |
| `sources/global_source.py` | `GlobalSource` | Used only in `report_builder.py` for morning report indices. Works but `ENABLE_MORNING_REPORT=False` by default so rarely triggered. |
| `telegram_bot.py` | `_handle_history()` | Handler exists (line 637) but **no command routes to it** in the `handle_updates_loop` router. `/history` command is unregistered. |
| `telegram_bot.py` | `_handle_upcoming()` | Handler exists (line 730) but returns "coming soon" stub. No live data behind it. |
| `nudge_manager.py` | `_nudge_inactive_users()` | Is a `pass` placeholder. `last_active_at` column not tracked in DB. |

---

## ❌ NOT WORKING / BROKEN

| Item | File | Issue |
|------|------|-------|
| Morning Pre-Market HTML Report | `report_builder.py` + `scheduler.py` | `ENABLE_MORNING_REPORT=False` in config (disabled by default). Report builder references `BulkDealSource` which is removed. Likely broken if enabled. |
| `/history` command | `telegram_bot.py` | Dead — handler coded but not wired in router. User sends `/history`, gets no response. |
| `/upcoming` command | `telegram_bot.py` | Returns hardcoded "coming soon". No data. |
| `v7_launcher.py` | Root | Old launch script from v7 migration. Probably stale, references old structure. |
| `migrate_v7.py` | Root | One-time DB migration script. Already ran. Leaving it is safe but it's clutter. |
| `watchdog_service.py` | Root | Standalone watchdog — **separate** from `watchdog.py` inside `nse_monitor/`. Unclear which is active. Likely the inner one. |
| Multiple `.bat` / `.sh` deploy scripts | Root | `deploy_prod.bat`, `deploy_to_windows.bat`, `run_all.bat`, `push_to_github.bat` — multiple overlapping scripts, unclear which is canonical for production. |

---

## 🏗️ ARCHITECTURE — How It Works

```
NSE / Media Scraper (every 3 min)
        ↓
  Dedup Check (URL hash + semantic block)
        ↓
  SQLite Queue (status=0 → PENDING)
        ↓
  Queue Worker (continuous, ~200ms loop)
        ↓
  [Market Hours?] → Stale Pruner (>4hr items = Expired)
        ↓
  Semaphore(5) → Sarvam 30B LLM (22-Rule Analysis)
        ↓
  Score < threshold? → status=1 (Filtered, no alert)
  Market OPEN + Score ≥ threshold? → status=2 → Telegram Alert ✅
  Market CLOSED + Score ≥ threshold? → status=3 → Morning Queue
        ↓
  8:30 AM next trading day → Morning Dispatch → Telegram ✅
```

---

## 📦 RUNTIME — Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | User signal bot token |
| `TELEGRAM_ADMIN_BOT_TOKEN` | ✅ | Separate admin panel bot token |
| `TELEGRAM_ADMIN_CHAT_ID` | ✅ | Owner's Telegram ID |
| `SARVAM_API_KEY` | ✅ | Sarvam AI API key |
| `RAZORPAY_KEY_ID` | ✅ | Razorpay key |
| `RAZORPAY_KEY_SECRET` | ✅ | Razorpay secret |
| `ADMIN_PASSWORD_HASH` | ✅ | Bcrypt hash of admin password |
| `ENABLE_MORNING_REPORT` | Optional | `0` (default) — HTML report disabled |
| `ENABLE_EMBEDDED_ADMIN_BOT` | Optional | `0` (default) — Use standalone admin_bot.py |
| `ALERT_POLICY_MODE` | Optional | `SENSITIVE_7PLUS` or `ULTRA_STRICT` |

---

## 🚀 DEPLOYMENT (VPS Ubuntu)

```bash
# 1. Pull latest
git pull

# 2. Install deps (if new)
pip install -r requirements.txt

# 3. Restart main bot
sudo systemctl restart nsebot

# 4. Start admin bot (separate process)
nohup ./.venv/bin/python admin_bot.py > admin_bot.log 2>&1 &

# 5. Watch logs
sudo journalctl -u nsebot -f | grep -E "(Hand-off|Stale|fetched|ingested|ERROR)"
```

### One-Time DB Queue Reset (if huge backlog)
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('nse_monitor/data/processed_announcements.db')
conn.execute(\"DELETE FROM news_items WHERE processing_status = 0\")
count = conn.execute('SELECT changes()').fetchone()[0]
conn.commit(); conn.close()
print(f'Cleared {count} stale pending items.')
"
```

---

## 📊 v3.1 PERFORMANCE FIXES (April 2026)

| Fix | Before | After |
|-----|--------|-------|
| `PRAGMA synchronous` | `FULL` (50ms/write) | `NORMAL` (0.5ms/write) |
| Queue batch size | 5 items | 10 items |
| LLM concurrency | Unbounded | `Semaphore(5)` |
| Stale item handling | None | Auto-expire >4hr items during market hours |

> **Result:** End-to-end news-to-Telegram latency reduced from 18+ hours to under 3 minutes.

---

## ⚖️ Disclaimer

Non-SEBI research automation tool. For informational and educational purposes only.
Bulkbeat TV is not a registered investment advisor. Trading involves risk.
