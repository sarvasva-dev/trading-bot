import requests
import time
import sys
import os

# Try to load token from nse_monitor/config.py or .env
try:
    # Add nse_monitor to path
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))
    from nse_monitor.config import TELEGRAM_BOT_TOKEN
except Exception:
    TELEGRAM_BOT_TOKEN = None

if not TELEGRAM_BOT_TOKEN:
    print("[ERROR] TELEGRAM_BOT_TOKEN not found in environment or config.")
    sys.exit(1)

def get_updates():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    print(f"\n[SYSTEM] Listening for messages sent to the bot...")
    print(f"[ACTION] Please send a message (like '/start') to your bot on Telegram now.")
    print("-" * 50)
    
    last_update_id = 0
    
    try:
        while True:
            params = {"offset": last_update_id + 1, "timeout": 30}
            response = requests.get(url, params=params, timeout=35)
            data = response.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update:
                        chat = update["message"]["chat"]
                        user = update["message"]["from"]
                        chat_id = chat["id"]
                        first_name = user.get("first_name", "N/A")
                        username = user.get("username", "N/A")
                        
                        print(f"\n✅ NEW USER DETECTED!")
                        print(f"Name: {first_name} (@{username})")
                        print(f"Chat ID: {chat_id}")
                        print(f"To add this user, copy the Chat ID above and add it to your .env file.")
                        print("-" * 50)
            
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOPPED] Chat ID listener closed.")

if __name__ == "__main__":
    get_updates()
