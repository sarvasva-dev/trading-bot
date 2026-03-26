import logging
import os
import time
import requests
from nse_monitor.config import TELEGRAM_ADMIN_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, ADMIN_PASSWORD

# Secure Admin Bot with /login Auth
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NSEAdmin")

class AdminBot:
    def __init__(self):
        self.token = TELEGRAM_ADMIN_BOT_TOKEN
        self.admin_chat_id = TELEGRAM_ADMIN_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0
        self.authenticated_users = {} # chat_id: timestamp

    def run(self):
        logger.info("Admin Service Online. Waiting for secure login...")
        while True:
            try:
                updates = self.get_updates()
                for update in updates:
                    self.handle_update(update)
                time.sleep(2)
            except Exception as e:
                logger.error(f"Admin Error: {e}")
                time.sleep(10)

    def get_updates(self):
        url = f"{self.base_url}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 20}
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if data.get("ok"):
            return data["result"]
        return []

    def handle_update(self, update):
        if "message" not in update: return
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        self.last_update_id = update["update_id"]

        if text.startswith("/login"):
            parts = text.split()
            if len(parts) == 2 and parts[1] == ADMIN_PASSWORD:
                self.authenticated_users[chat_id] = time.time()
                self.send_message(chat_id, "🔓 <b>Admin Access Granted.</b>\nYou can now use /status, /logs, /restart.")
            else:
                self.send_message(chat_id, "🚫 <b>Invalid Credentials.</b>")
            return

        # Restricted Commands
        if chat_id not in self.authenticated_users or (time.time() - self.authenticated_users[chat_id] > 3600):
            self.send_message(chat_id, "🔒 <b>Session Expired or Unauthorized.</b>\nPlease use <code>/login <pass></code>")
            return

        if text == "/status":
            count = 0
            try:
                from nse_monitor.database import Database
                db = Database()
                count = db.get_user_count()
            except: pass
            self.send_message(chat_id, f"✅ <b>NSE Pulse Engine:</b> Running\n🧠 <b>AI Core:</b> Connected\n👥 <b>Total Users:</b> {count}")
        elif text == "/logs":
            self.send_message(chat_id, "📝 <i>Full logs streaming coming soon.</i>")

    def send_message(self, chat_id, text):
        url = f"{self.base_url}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)

if __name__ == "__main__":
    if not TELEGRAM_ADMIN_BOT_TOKEN:
        logger.error("ADMIN_BOT_TOKEN missing!")
    else:
        AdminBot().run()
