# Bulkbeat TV v20.0 — Institutional Market Intelligence Engine

**Bulkbeat TV** is a high-precision, institutional-grade market intelligence engine designed for the Indian equities market (NSE). Engineered with a fully asynchronous architecture, it delivers real-time signals from corporate filings and institutional media, filtered through a strict 22-rule AI auditing protocol.

---

## 🛰️ Key Features (v20.0 Institutional Shield)

- **Autonomous Intelligence Pipeline**: Parallel ingestion from NSE, NSE SME, and high-tier institutional media.
- **Advanced AI Audit (Sarvam 30B)**: Real-time sentiment analysis and impact scoring (1-10) using state-of-the-art LLMs.
- **Institutional Shield Policy**: Strict alert threshold (Score ≥ 8) ensures only high-conviction signals reach subscribers.
- **Real-Time Admin Governance**: Instant configuration of AI sensitivity and media sources via a secure Admin Control Panel.
- **Zero-Loss Data Queue**: SQLite-WAL-backed persistence ensuring zero data drop during high-volatility market bursts.
- **Smart Money Tracking**: Automated institutional flow analysis for high-impact market events.
- **Dynamic Community Broadcasts**: Professional notification system with customizable headers (e.g., `ANNUNCIATION`, `TEST`, `SUMMARY`).

---

## 🏛️ Administrative Governance

The system features a decoupled **Admin Control Panel** for real-time mission control:

- **Threshold Management**: Adjust AI strictness instantly (4/6/8 sensitivity scale).
- **Media Mute**: Toggle official institutional filings vs. general media signals.
- **Dynamic Broadcasts**: Send formatted signals to the entire user base using the pipe separator syntax:
  - `/broadcast TITLE | YOUR_MESSAGE`
- **User Auditing**: Real-time management of active subscriptions and credit balances.

---

## 🛠️ Quick Deployment (Institutional VPS)

### 1. Environment Setup
```bash
git clone <repository_url>
cd nse2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Service Initialization
The system runs as a `systemd` service for 99.9% uptime.
```bash
# Definitive Institutional Sync & Restart
git pull origin main && pkill -f admin_bot.py && sudo systemctl restart nsebot && nohup python admin_bot.py > admin_bot.log 2>&1 &
```

---

## 📊 Operations & Monitoring
- **Admin Dashboard**: Accessible via the dedicated Admin Bot.
- **Log Audit**: `tail -f nse_monitor/logs/service.log`
- **Data Persistence**: `nse_monitor/data/processed_announcements.db`
- **Service Status**: `sudo systemctl status nsebot`

---

## ⚖️ Disclaimer
*Non-SEBI Research Tool. Content is for educational and informational purposes only. Trading involves substantial risk. Consultation with certified professionals is advised. Bulkbeat TV is an AI-augmented automation suite providing high-speed information processing.*
