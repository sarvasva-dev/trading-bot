# Bulkbeat TV v2.0 (Institutional Pro)

High-precision Indian market intelligence engine. Fully async architecture engineered to run 24/7 on a 1GB Linux VPS with zero-loss data ingestion and ultra-strict AI signal generation.

## 🏛️ v2.0 Core Features
- **Fully Async Engine**: `asyncio`-native core — no ThreadPool, no blocking I/O.
- **5-Source Intelligence Pipeline**: NSE, NSE SME, Bulk Deals, Economic Times, Moneycontrol (ingest-only).
- **AI Model**: Sarvam 30B (`sarvam-30b`) — 22-Rule Institutional Engine.
- **Ultra-Strict Alert Policy (`ULTRA_STRICT_8PLUS`)**: Live alerts only for score ≥ 8 from whitelisted sources (NSE, NSE_SME, NSE_BULK).
- **Smart Money Analysis**: Institutional flow detection triggered for signals scoring ≥ 7.
- **Impact Tracker**: Post-alert price tracking to measure signal accuracy.
- **Nudge Manager**: Automated re-engagement nudges for inactive subscribers.
- **Symbol Cooldown**: 90-min per-symbol cooldown to prevent alert spam.
- **Daily Alert Budget**: Soft target 5, hard cap 10 (score ≥ 9 bypasses cap).
- **Post-Market Suppression**: After market hours, only score = 10 alerts fire.
- **Pulse Monitoring**: `/pulse` — live RAM, Disk, DB stats via Admin Bot.
- **Campaign Tracking**: Deep-linked referral tags (e.g. `t.me/bot?start=ad_101`).
- **SQLite WAL Mode**: 30s busy-timeout for high-concurrency writes.
- **Safe OCR Pipeline**: Serial Tesseract OCR at 120 DPI for RAM-constrained VPS.
- **Automated Hot-Backups**: Daily SQLite Online Backup API snapshots (5 retained).
- **Single-Instance Lock**: PID file guard prevents duplicate bot processes.

## 🛠️ Deployment

### 1. System Preparation
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tesseract-ocr -y
```

### 2. Installation
```bash
git clone <your_repo_url>
cd nse2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration (`.env`)
```env
# Core
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_ADMIN_BOT_TOKEN=your_admin_token
TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id
SARVAM_API_KEY=your_sarvam_key
ADMIN_PASSWORD=your_dashboard_pass

# Alert Policy (optional overrides)
ALERT_POLICY_MODE=ULTRA_STRICT_8PLUS
DAILY_ALERT_HARD_CAP=10
SYMBOL_COOLDOWN_MIN=90
NEUTRAL_BLOCK=1
ALLOWED_LIVE_SOURCES=NSE,NSE_SME,NSE_BULK

# Payment (optional)
RAZORPAY_KEY_ID=your_raz_key
RAZORPAY_KEY_SECRET=your_raz_sec
```

### 4. Database Migration
```bash
python migrate_v7.py
```

### 5. Service Management (Systemd)
```bash
sudo cp nsebot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nsebot
sudo systemctl start nsebot
```

## 📊 Operations
- **Health Check**: `python -m nse_monitor.main --health`
- **Logs**: `nse_monitor/logs/app.log` (rotating, max 5MB × 3)
- **Database**: `nse_monitor/data/processed_announcements.db`
- **Backups**: `nse_monitor/data/backups/` (5 copies retained)
- **Admin Bot**: `/pulse`, `/broadcast`, `/grant`
- **User Bot**: `/hisab` (billing audit), `/bulk`, `/upcoming`

## ⚖️ Disclaimer
*Non-SEBI Research Tool. Educational purposes only. Users assume all risk for financial decisions.*
