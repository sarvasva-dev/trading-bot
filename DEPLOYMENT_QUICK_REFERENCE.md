# Deployment Quick Reference

## 1. Install

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git tesseract-ocr -y

git clone <repository_url>
cd trading-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Update Code

If `.env` is locally modified:

```bash
git stash push -m "local-env" .env
git pull origin main
git stash pop
```

## 3. Restart Services

```bash
sudo systemctl restart nsebot
pkill -f admin_bot.py || true
nohup ./.venv/bin/python admin_bot.py > admin_bot.log 2>&1 &
```

## 4. Verify

```bash
sudo systemctl status nsebot --no-pager -l
pgrep -af "python -m nse_monitor.main"
pgrep -af "admin_bot.py"
tail -n 80 nse_monitor/logs/app.log
tail -n 80 admin_bot.log
```

## 5. Queue Snapshot

```bash
./.venv/bin/python - <<'PY'
import sqlite3
c=sqlite3.connect('nse_monitor/data/processed_announcements.db').cursor()
for st in [0,1,2,3,9]:
    c.execute("select count(*) from news_items where processing_status=?", (st,))
    print(st, c.fetchone()[0])
PY
```

## 6. Safety Notes

- Keep only one admin bot process.
- Keep `ENABLE_EMBEDDED_ADMIN_BOT=0` unless intentionally needed.
- Rotate Telegram token immediately if exposed.
