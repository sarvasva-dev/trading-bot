# VPS Deployment Guide (Ubuntu 22.04, 1GB RAM)

## Preconditions

- SSH access
- `.env` prepared with valid tokens/keys
- recent DB backup available

## 1. Host Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tesseract-ocr -y
```

## 2. App Setup

```bash
git clone <repository_url> trading-bot
cd trading-bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Systemd Service (`nsebot`)

Use `.venv` in service command.

```ini
[Unit]
Description=Bulkbeat TV Intelligence Engine
After=network.target

[Service]
Type=simple
User=ipynb
WorkingDirectory=/home/ipynb/trading-bot
EnvironmentFile=/home/ipynb/trading-bot/.env
ExecStart=/home/ipynb/trading-bot/.venv/bin/python -m nse_monitor.main
Environment="PYTHONUNBUFFERED=1"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nsebot
sudo systemctl restart nsebot
```

## 4. Admin Bot (Standalone)

```bash
pkill -f admin_bot.py || true
nohup ./.venv/bin/python admin_bot.py > admin_bot.log 2>&1 &
```

## 5. Permissions Fix (If DB Becomes Readonly)

```bash
sudo systemctl stop nsebot
pkill -f admin_bot.py || true
sudo chown -R ipynb:ipynb /home/ipynb/trading-bot
sudo chmod -R u+rwX /home/ipynb/trading-bot/nse_monitor/data
sudo systemctl start nsebot
nohup /home/ipynb/trading-bot/.venv/bin/python /home/ipynb/trading-bot/admin_bot.py > /home/ipynb/trading-bot/admin_bot.log 2>&1 &
```

## 6. Operational Checks

```bash
sudo systemctl status nsebot --no-pager -l
pgrep -af "python -m nse_monitor.main"
pgrep -af "admin_bot.py"
tail -n 100 nse_monitor/logs/app.log
tail -n 100 admin_bot.log
```

## 7. Runtime Defaults

- Ingestion interval: every 3 minutes
- Live market window: 08:30 to 15:30 IST
- Morning queued dispatch: 08:30 IST
- Morning report: disabled by default
- Embedded admin bot: disabled by default

## 8. 1GB RAM Notes

- Keep threshold at 8 for low-noise stability.
- Keep single admin process only.
- Monitor queue statuses and avoid process duplication.
