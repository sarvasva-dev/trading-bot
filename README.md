# Market Pulse v1.3.3 (Institutional Pro)

High-precision Indian market intelligence engine designed for Institutional-grade analysis. Engineered to run 24/7 on an optimized 1GB Linux VPS with zero-loss data ingestion and high-impact AI signal generation.

## 🏛️ v1.3.3 Institutional Features
- **Professional Dashboard**: High-impact English UI designed for clarity and value perception.
- **Pulse Monitoring**: Real-time server health monitoring (`/pulse`) including RAM, Disk, and DB stats.
- **Campaign Tracking**: Native support for deep-linked marketing tags (e.g., `t.me/bot?start=ad_101`) to track conversion ROI.
- **Industrial DB Scalability**: Powered by **SQLite WAL (Write-Ahead Logging)** with 30s busy-timeouts for high-concurrency workloads.
- **Safe OCR Pipeline**: RAM-safe serial OCR processing (120 DPI) optimized for low-resource environments.
- **Automated Hot-Backups**: Daily point-in-time database snapshots using the SQLite Online Backup API.

## 🛠️ Deployment (Institutional Setup)

### 1. System Preparation
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tesseract-ocr -y
```

### 2. Installation
```bash
git clone <your_repo_url>
cd <repo_dir>
python3 -m venv venv
home/user/venv/bin/pip install -r requirements.txt
```

### 3. Environment Configuration (`.env`)
```env
# 🛰️ Core API Keys
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_ADMIN_BOT_TOKEN=your_admin_token
SARVAM_API_KEY=your_sarvam_key
ADMIN_PASSWORD=your_dashboard_pass

# 💳 Payment (Optional)
RAZORPAY_KEY_ID=your_raz_key
RAZORPAY_KEY_SECRET=your_raz_sec
```

### 4. Service Management (Systemd)
The bot is designed to run as a persistent background service.

```bash
sudo cp nsebot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nsebot
sudo systemctl start nsebot
```

## 📊 Operations & Auditing
- **General Health**: Admin Bot command `/pulse`
- **Signal Logs**: `data/logs/app.log` (Auto-rotating, Max 5MB)
- **Database**: `nse_monitor/data/processed_announcements.db`
- **Backups**: `nse_monitor/data/backups/` (Auto-retained 5 copies)
- **Billing Audit**: User Bot command `/hisab` (Institutional Daily Audit)

## ⚖️ Disclaimer
*Non-SEBI Research Tool. Content for educational purposes only. Market Pulse is an intelligence automation system; users assume all risk for financial decisions.*
