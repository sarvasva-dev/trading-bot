# Market Intelligence Bot v7.0 (Event-Driven)

Sophisticated Indian market intelligence engine with semantic event clustering, hybrid impact scoring, and automated reporting.

## 🚀 v7.0 Features
- **Semantic Clustering**: Groups related news using `all-MiniLM-L6-v2`.
- **Hybrid Impact Scoring**: AI analysis + Rule-based logic (RBI, Interest Rates, War, M&A).
- **Alert Policy**: Smart high-impact alerts (>=85 market hours, >=90 after).
- **Rate Limiting**: Maximum 3 alerts per hour to prevent noise.
- **Pre-Market Reports**: Consolidated intelligence reports every morning at 08:30 IST.
- **Weekday Focus**: Automatic weekend suspension.

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
Description=Market Intelligence Bot v7.0
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
