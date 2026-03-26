import logging
import requests
import time
import os
import json
import html
from datetime import datetime
import pytz
from nse_monitor.config import TELEGRAM_ADMIN_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, ADMIN_PASSWORD, BOT_NAME
from nse_monitor.database import Database

# Logging Setup
def ist_time(*args):
    return datetime.now(pytz.timezone('Asia/Kolkata')).timetuple()

logging.Formatter.converter = ist_time
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("NSEAdmin")

class AdminPanel:
    def __init__(self):
        self.token = TELEGRAM_ADMIN_BOT_TOKEN
        self.owner_id = str(TELEGRAM_ADMIN_CHAT_ID)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = Database()
        self.last_update_id = 0
        self.authenticated_sessions = {} # chat_id: timestamp
        self._set_latest_offset()

    def _set_latest_offset(self):
        """Skip all stale messages on startup (Rule #24)."""
        try:
            r = requests.get(f"{self.base_url}/getUpdates", params={"offset": -1, "limit": 1}, timeout=5)
            data = r.json()
            if data.get("ok") and data.get("result"):
                self.last_update_id = data["result"][0]["update_id"]
                logger.info(f"Admin Bot Offset Synced: {self.last_update_id}")
        except: pass

    def is_admin(self, chat_id):
        cid = str(chat_id)
        # 1. Owner bypass
        if cid == self.owner_id: return True
        # 2. Session check (60 mins)
        session_time = self.authenticated_sessions.get(cid, 0)
        return (time.time() - session_time) < 3600

    def run(self):
        logger.info(f"--- {BOT_NAME} ADMIN PANEL ONLINE ---")
        if self.owner_id:
            logger.info(f"Owner Auto-Login: {self.owner_id}")
        
        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self.last_update_id = update["update_id"]
                    if "message" in update:
                        self._handle_message(update["message"])
                    elif "callback_query" in update:
                        self._handle_callback(update["callback_query"])
                time.sleep(1)
            except Exception as e:
                logger.error(f"Admin Main Loop Error: {e}")
                time.sleep(5)

    def _get_updates(self):
        url = f"{self.base_url}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 20}
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        return data.get("result", []) if data.get("ok") else []

    def _handle_message(self, msg):
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        
        # 1. Login Logic
        if text.startswith("/login"):
            parts = text.split()
            if len(parts) == 2 and parts[1] == ADMIN_PASSWORD:
                self.authenticated_sessions[chat_id] = time.time()
                self._send(chat_id, "🔓 <b>Authentication Successful!</b>\nYou now have 60 minutes of admin access.")
                self._send_main_menu(chat_id)
            else:
                self._send(chat_id, "🚫 <b>Invalid Credentials.</b>")
            return

        # 2. Admin Command Guard
        if not self.is_admin(chat_id):
            self._send(chat_id, "🔒 <b>Access Denied.</b>\nPlease use <code>/login <password></code>")
            return

        # 3. Command Router
        if text == "/start" or text == "/admin":
            self._send_main_menu(chat_id)
        elif text == "/list":
            self._handle_list(chat_id)
        elif text == "/status":
            self._handle_status(chat_id)
        elif text == "/users":
            self._handle_users(chat_id)
        elif text.startswith("/grant"):
            self._handle_grant(chat_id, text)
        elif text.startswith("/broadcast"):
            self._handle_broadcast(chat_id, text)

    def _handle_callback(self, cb):
        from_id = str(cb["from"]["id"])
        chat_id = from_id # Private chat context
        data = cb["data"]
        
        if not self.is_admin(from_id):
            self._answer_callback(cb["id"], "Session Expired! Please login.")
            return

        if data == "menu_status":
            self._handle_status(chat_id)
        elif data == "menu_list" or data == "menu_users":
            self._handle_list(chat_id)
        elif data == "menu_broadcast":
            self._send(chat_id, "📢 Usage: <code>/broadcast &lt;message&gt;</code>\nThis will notify ALL active subscribers.")
        
        self._answer_callback(cb["id"])

    def _send_main_menu(self, chat_id):
        text = (
            f"🛠️ <b>{BOT_NAME} ADMIN GUIDE (v8.7)</b>\n"
            f"────────────────────────\n"
            f"<b>Commands:</b>\n"
            f"• <code>/list</code> — Full User Audit Log\n"
            f"• <code>/grant &lt;id&gt; &lt;days&gt;</code> — Manual Credit\n"
            f"• <code>/broadcast &lt;msg&gt;</code> — Global Alert\n"
            f"• <code>/status</code> — System Health Check\n\n"
            f"<b>Key Indicators:</b>\n"
            f"💎 = Active Premium | 🆓 = Free/Trial\n\n"
            f"Select an action below for quick access:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 System Status", "callback_data": "menu_status"}],
                [{"text": "📋 Full User List", "callback_data": "menu_list"}],
                [{"text": "📢 Mass Broadcast", "callback_data": "menu_broadcast"}]
            ]
        }
        self._send(chat_id, text, keyboard)

    def _handle_status(self, chat_id):
        total, active = self.db.get_user_stats()
        text = (
            f"📊 <b>PRODUCTION STATUS (v8.7)</b>\n"
            f"────────────────────────\n"
            f"✅ <b>Signal Engine:</b> ACTIVE\n"
            f"🧠 <b>AI Processor:</b> ONLINE\n\n"
            f"👥 <b>Total Users:</b> {total}\n"
            f"⚡ <b>Active Subs:</b> {active}\n"
            f"────────────────────────\n"
            f"📍 <i>Build: Institutional Prime</i>"
        )
        self._send(chat_id, text)

    def _handle_list(self, chat_id):
        """Highly detailed user audit list (v8.7)."""
        users = self.db.get_all_users(limit=50)
        text = "📋 <b>INSTITUTIONAL USER AUDIT</b>\n────────────────────────\n"
        
        for u in users:
            uid, name, uname, active, days = u
            username_safe = f"(@{uname})" if uname and uname != "manual_entry" else ""
            status_text = "ACTIVE" if active else "OFF"
            icon = "💎" if active else "🆓"
            
            # Estimate Plan Logic
            plan_name = "Trial"
            if days >= 336: plan_name = "Insti"
            elif days >= 28: plan_name = "Pro"
            elif days >= 7: plan_name = "Grth"
            elif days >= 2: plan_name = "Star"
            
            text += f"{icon} <b>{name}</b> {username_safe} [<code>{uid}</code>]\n"
            text += f"   └ Status: {status_text} | Bal: <b>{days}d</b> ({plan_name})\n\n"
        
        if not users:
            text += "<i>No users found in database.</i>"
            
        text += "────────────────────────\n"
        text += "💡 <i>Use /grant &lt;id&gt; &lt;days&gt; to credit.</i>"
        self._send(chat_id, text)

    def _handle_users(self, chat_id):
        users = self.db.get_all_users(limit=15)
        text = "👥 <b>LATEST USERS (AUDIT)</b>\n────────────────────────\n"
        for u in users:
            uid, name, uname, active, days = u
            icon = "💎" if active else "🆓"
            text += f"{icon} {name} (<code>{uid}</code>) | {days}d\n"
        
        text += "\n💡 <i>To modify: /grant <id> <days></i>"
        self._send(chat_id, text)

    def _handle_grant(self, chat_id, text):
        parts = text.split()
        if len(parts) < 3:
            self._send(chat_id, "⚠️ Usage: <code>/grant <id> <days></code>")
            return
        
        target_id, days = parts[1], parts[2]
        self.db.add_working_days(target_id, int(days))
        self.db.toggle_user_status(target_id, 1)
        self._send(chat_id, f"✅ <b>Granted {days} days to {target_id}.</b> User is now ACTIVE.")

    def _handle_broadcast(self, chat_id, text):
        msg_body = text.replace("/broadcast", "").strip()
        if not msg_body:
            self._send(chat_id, "⚠️ No message content provided.")
            return

        active_users = self.db.get_active_users()
        count = 0
        for uid in active_users:
            try:
                self._send(uid, f"📢 <b>ADMIN ANNOUNCEMENT</b>\n────────────────────────\n{msg_body}")
                count += 1
                time.sleep(0.05)
            except: pass
        self._send(chat_id, f"✅ <b>Broadcast complete.</b> Sent to {count} users.")

    def _send(self, chat_id, text, keyboard=None):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if keyboard: payload["reply_markup"] = keyboard
        requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)

    def _answer_callback(self, cb_id, text=None):
        payload = {"callback_query_id": cb_id}
        if text: payload["text"] = text
        requests.post(f"{self.base_url}/answerCallbackQuery", json=payload, timeout=5)

if __name__ == "__main__":
    AdminPanel().run()
