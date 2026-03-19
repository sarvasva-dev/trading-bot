# Market Pulse v1.0 (Market Intelligence Engine)

Sophisticated Indian market intelligence engine with AI synthesis, hybrid impact scoring, and automated reporting.

## 🚀 v1.0 Features (Optimized)
- **Pulse Synthesis**: New Executive summaries for morning reports.
- **RAM Balanced**: Optimized for 1GB VPS (Low memory footprint).
- **Multi-Source**: Tracks NSE announcements, MoneyControl, and Economic Times.
- **Hybrid Impact Scoring**: AI analysis + Rule-based logic.
- **Rate Limiting**: Maximum 5 alerts per hour (Spam Protection).
- **IST Precision**: Consolidated reports at 08:30 IST.
- **Weekday Focus**: Automatic weekend suppression for alerts.

## 🛠️ Linux VPS Deployment (Ubuntu/Debian)

### 1. System Preparation
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git -y
```

### 2. Installation
```bash
git clone https://github.com/sitekraft/Trading-bot.git
cd Trading-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Setup
Create a `.env` file at the root:
```env
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_IDS=["id1", "id2"]
DEEPSEEK_API_KEY=your_deepseek_key
DeepSeek V3 (via OpenAI SDK)
```

### 4. Running with Systemd (Recommended)
Create a service file:
```bash
sudo nano /etc/systemd/system/nsebot.service
```

Paste this:
```ini
[Unit]
Description=Market Pulse Intelligence Bot v1.0
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/Trading-bot
ExecStart=/path/to/Trading-bot/venv/bin/python v7_launcher.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable nsebot
sudo systemctl start nsebot
sudo systemctl status nsebot
```

## 📊 Operations
- **Logs**: check `data/logs/app.log`.
- **Data**: check `data/nse_monitor.db`.
