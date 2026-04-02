# nse_monitor — Core Intelligence Engine (v2.0)

## Setup

1. `.env` in project root:
   ```env
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_ADMIN_BOT_TOKEN=your_admin_token
   TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id
   SARVAM_API_KEY=your_sarvam_key
   ADMIN_PASSWORD=your_password
   ```

2. Install:
   ```bash
   pip install -r requirements.txt
   ```

3. Migrate DB:
   ```bash
   python migrate_v7.py
   ```

4. Run:
   ```bash
   python -m nse_monitor.main
   # Health check only:
   python -m nse_monitor.main --health
   ```

## Module Map

| File | Role |
|------|------|
| `main.py` | Async core — `MarketIntelligenceSystem`, boot, cycle loop |
| `config.py` | All env vars, policy constants, subscription plans |
| `scheduler.py` | APScheduler AsyncIO — 7 jobs |
| `database.py` | SQLite WAL, all DB operations, backup |
| `llm_processor.py` | Sarvam AI integration — scoring & sentiment |
| `pdf_processor.py` | PDF download + Tesseract OCR |
| `market_analyzer.py` | Smart money / institutional flow analysis |
| `impact_tracker.py` | Post-alert price movement tracking |
| `nudge_manager.py` | Inactive user re-engagement |
| `report_builder.py` | Morning pre-market report generator |
| `telegram_bot.py` | User-facing bot (signals, billing, commands) |
| `telegram_notifier.py` | Low-level Telegram send utility |
| `nse_api.py` | Async NSE API client |
| `trading_calendar.py` | NSE holiday detection |
| `watchdog.py` | Service health monitor |
| `payment_processor.py` | Razorpay payment verification |

## Sources (`sources/`)

| File | Source | Alert Eligible |
|------|--------|---------------|
| `nse_source.py` | NSE Corporate Filings | ✅ |
| `nse_sme_source.py` | NSE SME Filings | ✅ |
| `bulk_deal_source.py` | NSE Bulk/Block Deals (≥ ₹5 Cr) | ✅ |
| `economic_times_source.py` | Economic Times | ❌ Ingest-only |
| `moneycontrol_source.py` | Moneycontrol | ❌ Ingest-only |

## Directory Structure
- `data/` — SQLite DB + backups + holiday JSON
- `downloads/` — Cached PDF filings
- `logs/` — Rotating app log (5MB × 3)
