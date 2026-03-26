import logging
import requests
import time
import html
import os
import json
from nse_monitor.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, BOT_NAME, ADMIN_PASSWORD

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, db=None):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_ids = [str(cid) for cid in TELEGRAM_CHAT_IDS] if TELEGRAM_CHAT_IDS else []
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0
        self.db = db
        self.dynamic_ids_file = "data/dynamic_chat_ids.json"
        self.admin_sessions = {} # chat_id: timestamp
        self._load_dynamic_ids()
        self._sync_with_db()

    def _load_dynamic_ids(self):
        """Loads IDs from JSON storage."""
        if os.path.exists(self.dynamic_ids_file):
            try:
                with open(self.dynamic_ids_file, "r") as f:
                    data = json.load(f)
                    extra_ids = data if isinstance(data, list) else data.get("ids", [])
                    for cid in extra_ids:
                        cid_str = str(cid)
                        if cid_str not in self.chat_ids:
                            self.chat_ids.append(cid_str)
            except Exception as e:
                logger.error(f"Error loading dynamic chat IDs: {e}")

    def _sync_with_db(self):
        """Ensures all JSON IDs are also persisted in the SQLite users table."""
        if not self.db: return
        logger.info("Syncing User Database...")
        for chat_id in self.chat_ids:
            self.db.save_user(chat_id, "Sync_Legacy", "Legacy")

    def _save_dynamic_ids(self, chat_id=None, first_name=None, username=None):
        """Saves a new user to both JSON and DB (Rule #24)."""
        if chat_id and str(chat_id) not in self.chat_ids:
            self.chat_ids.append(str(chat_id))
            if self.db:
                self.db.save_user(chat_id, first_name, username)

        os.makedirs(os.path.dirname(self.dynamic_ids_file), exist_ok=True)
        try:
            with open(self.dynamic_ids_file, "w") as f:
                json.dump(list(set([str(cid) for cid in self.chat_ids])), f)
        except Exception as e:
            logger.error(f"Error saving dynamic IDs: {e}")

    def register_menu_commands(self):
        """Registers the bot commands in the Telegram menu."""
        url = f"{self.base_url}/setMyCommands"
        commands = [
            {"command": "start", "description": "Activate Engine & Legal Disclaimer"},
            {"command": "login", "description": "Admin Authentication (Password Required)"},
            {"command": "status", "description": "Admin: System & User Stats"},
            {"command": "bulk", "description": "Latest Bulk/Block Deal Intel"},
            {"command": "upcoming", "description": "Upcoming Corporate Actions"}
        ]
        try:
            requests.post(url, json={"commands": commands}, timeout=10)
        except Exception as e:
            logger.error(f"Failed to register commands: {e}")

    def handle_updates(self):
        """Checks for new messages and handles commands."""
        if not self.token: return
        
        try:
            url = f"{self.base_url}/getUpdates"
            params = {"offset": self.last_update_id + 1, "timeout": 1}
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    self.last_update_id = update["update_id"]
                    if "message" in update:
                        chat_id = str(update["message"]["chat"]["id"])
                        text = update["message"].get("text", "").strip()
                        first_name = update["message"]["from"].get("first_name", "User")
                        
                        # 1. Registration Logic
                        if chat_id not in self.chat_ids:
                            username = update["message"]["from"].get("username", "Unknown")
                            self._save_dynamic_ids(chat_id, first_name, username)
                            logger.info(f"New User Registered: {first_name} (@{username}) | ID: {chat_id}")

                        # 2. Command Router
                        if text == "/start":
                            self._send_welcome(chat_id, first_name)
                        elif text.startswith("/login"):
                            self._handle_login(chat_id, text)
                        elif text == "/status":
                            self._handle_status(chat_id)
                        elif text == "/bulk":
                            self._handle_bulk_deals(chat_id)
                        elif text == "/upcoming":
                            self._handle_upcoming(chat_id)

        except Exception as e:
            logger.error(f"Failed to handle Telegram updates: {e}")

    def _send_welcome(self, chat_id, first_name):
        welcome_text = (
            f"🚀 <b>{BOT_NAME} Online</b>\n\n"
            f"Hello {first_name}! I am your high-precision NSE intelligence engine.\n\n"
            f"<b>Core Capabilities:</b>\n"
            f"• Direct Institutional Corporate Filings\n"
            f"• Real-time high-impact signals (>7 Score)\n"
            f"• Bulk/Block Deal intelligence\n\n"
            f"⚖️ <b>SEBI DISCLAIMER:</b>\n"
            f"<i>This automated engine is for INFORMATIONAL & EDUCATIONAL purposes only. "
            f"Content does not constitute financial, legal, or investment advice. "
            f"We are NOT SEBI Registered advisors. Trading carries substantial risk; "
            f"please consult a certified professional before taking any action.</i>"
        )
        self._send_raw(chat_id, welcome_text)

    def _handle_login(self, chat_id, text):
        parts = text.split()
        if len(parts) < 2:
            self._send_raw(chat_id, "❌ Usage: <code>/login <password></code>")
            return
            
        provided_password = parts[1]
        if provided_password == ADMIN_PASSWORD:
            self.admin_sessions[str(chat_id)] = time.time()
            self._send_raw(chat_id, "🔓 <b>Admin Authentication Successful.</b>\nYou now have elevated privileges for this session.")
            logger.warning(f"ADMIN LOGIN: {chat_id}")
        else:
            self._send_raw(chat_id, "🚫 <b>Invalid Password.</b> Access Denied.")
            logger.error(f"FAILED LOGIN ATTEMPT: {chat_id}")

    def _handle_status(self, chat_id):
        if not self.is_admin(chat_id):
            self._send_raw(chat_id, "🔒 <b>Session Expired or Unauthorized.</b>\nPlease use <code>/login <pass></code>")
            return
            
        count = self.db.get_user_count() if self.db else 0
        status_text = (
            f"📊 <b>SYSTEM STATUS</b>\n"
            f"────────────────────────\n"
            f"✅ <b>Signal Engine:</b> ACTIVE\n"
            f"🧠 <b>AI Processor:</b> ONLINE\n"
            f"👥 <b>Total Synced Users:</b> {count}\n"
            f"────────────────────────\n"
            f"📍 <i>Server: Institutional v7.5</i>"
        )
        self._send_raw(chat_id, status_text)

    def _handle_bulk_deals(self, chat_id):
        # Placeholder for real DB query from BulkDealSource
        msg = "📊 <b>Latest Bulk Deal Intelligence</b>\n<i>Coming soon: Streamed from NSE x Moneycontrol</i>"
        self._send_raw(chat_id, msg)

    def _handle_upcoming(self, chat_id):
        msg = "🗓️ <b>Upcoming High-Impact Triggers</b>\n<i>Monitoring: Mergers, Splits & Dividend Record Dates.</i>"
        self._send_raw(chat_id, msg)

    def is_admin(self, chat_id):
        # Session valid for 4 hours
        session_time = self.admin_sessions.get(str(chat_id), 0)
        return (time.time() - session_time) < 14400

    def _send_raw(self, chat_id, text):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "protect_content": True # RULE #23: Prevent forwarding
        }
        try:
            requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Raw send failed: {e}")

    def send_report(self, report_text):
        """Sends a structured pre-market report."""
        if not self.token or not self.chat_ids: return

        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": report_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "protect_content": True
            }
            try:
                requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=20)
            except Exception as e:
                logger.error(f"Failed to send report to {chat_id}: {e}")
        logger.info(f"Broadcasted report to {len(self.chat_ids)} users.")

    def send_alert(self, data):
        """Sends a high-precision market alert with SEBI disclaimer."""
        if not self.token or not self.chat_ids: return

        report = data.get("ai_report") or {}
        symbol = html.escape(str(data.get("symbol", "N/A")))
        trigger = html.escape(str(data.get("trigger", "N/A")))
        
        impact_score = data.get("impact_score", "N/A")
        sentiment = html.escape(str(data.get("sentiment", "Neutral")))
        url = data.get("url")
        if url and not url.startswith("http"):
            url = f"https://nsearchives.nseindia.com/corporate/{url}"

        # RULE #21: Precision Format
        message = (
            f"🛰️ <b>{symbol.upper()}</b> | Signal Engine\n"
            f"────────────────────────\n"
            f"🎯 <b>TRIGGER:</b> {trigger}\n"
            f"📊 <b>IMPACT:</b> {impact_score}/10\n"
            f"🧠 <b>SENTIMENT:</b> {sentiment}\n"
            f"────────────────────────\n"
            f"👉 <a href='{url or '#'}'>Reference Filing</a>\n\n"
            f"⚖️ <i>Non-SEBI Educational Resource</i>"
        )

        success = False
        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "protect_content": True
            }
            try:
                r = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
                if r.status_code == 200: success = True
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
            
        return success
