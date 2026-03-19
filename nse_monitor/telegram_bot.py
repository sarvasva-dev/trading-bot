import logging
import requests
import time
import html
import os
import json
from nse_monitor.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, BOT_NAME

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        # Ensure we work with a mutable list rather than a tuple or strict config ref
        self.chat_ids = list(TELEGRAM_CHAT_IDS) if TELEGRAM_CHAT_IDS else []
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0
        self.dynamic_ids_file = "data/dynamic_chat_ids.json"
        self._load_dynamic_ids()

    def _load_dynamic_ids(self):
        if os.path.exists(self.dynamic_ids_file):
            try:
                with open(self.dynamic_ids_file, "r") as f:
                    extra_ids = json.load(f)
                    for cid in extra_ids:
                        if cid not in self.chat_ids:
                            self.chat_ids.append(cid)
            except Exception as e:
                logger.error(f"Error loading dynamic chat IDs: {e}")

    def _save_dynamic_ids(self):
        os.makedirs(os.path.dirname(self.dynamic_ids_file), exist_ok=True)
        try:
            with open(self.dynamic_ids_file, "w") as f:
                json.dump(list(set(self.chat_ids)), f)
        except Exception as e:
            logger.error(f"Error saving dynamic IDs: {e}")

    def handle_updates(self):
        """Checks for new messages and sends a welcome message for the first interaction."""
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
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"].get("text", "").strip()
                        first_name = update["message"]["from"].get("first_name", "User")
                        
                        # Register new users dynamically
                        is_new_user = False
                        if chat_id not in self.chat_ids:
                            self.chat_ids.append(chat_id)
                            self._save_dynamic_ids()
                            is_new_user = True
                            logger.info(f"Dynamically registered new user: {first_name} ({chat_id})")
                            
                        # Response Logic: Welcome on New User OR Explicit /start command
                        if is_new_user or text == "/start":
                            # Send Welcome Message
                            welcome_text = (
                                f" 🛰️ <b>{BOT_NAME} Activated</b>\n\n"
                                f"Hello {first_name}! I am your high-frequency intelligence engine.\n\n"
                                f" <b>Sources tracked:</b>\n"
                                f"• NSE (Direct Filings)\n"
                                f"• MoneyControl & Economic Times\n\n"
                                f" <b>What to expect:</b>\n"
                                f"⚡ <b>Real-time Alerts:</b> High-impact news during market hours.\n"
                                f"🌅 <b>Morning Recap:</b> Consolidated intelligence at 08:30 IST.\n"
                                f"🧠 <b>AI Analysis:</b> Every event is cross-verified for impact."
                            )
                            self._send_raw(chat_id, welcome_text)

        except Exception as e:
            logger.error(f"Failed to handle Telegram updates: {e}")

    def check_user_subscription(self, chat_id):
        """
        [PAYMENT PLACEHOLDER]
        Checks if the user has an active subscription.
        Currently returns True (Free Tier).
        Integration Point: Connect this to Razorpay/Stripe database checks.
        """
        # TODO: Implement database lookup for user payment status
        # return self.db.is_premium_user(chat_id)
        return True 

    def _send_raw(self, chat_id, text):
        """Internal helper for sending basic text messages."""
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            r = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            if r.status_code != 200:
                logger.error(f"Raw send failed ({r.status_code}): {r.text}")
        except Exception as e:
            logger.error(f"Raw send failed: {e}")

    def send_report(self, report_text):
        """Sends a structured pre-market report to all configured Telegram recipients."""
        if not self.token or not self.chat_ids:
            logger.warning("Telegram configuration missing (no token or chat_ids). Skipping report.")
            return

        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": report_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }

            try:
                logger.debug(f"Sending report to chat_id: {chat_id}")
                r = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=20)
                r.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to send report to {chat_id}: {e}")
        
        logger.info(f"Broadcasted report to {len(self.chat_ids)} users.")

    def send_alert(self, data):
        """Sends a premium market alert to all configured Telegram recipients."""
        if not self.token or not self.chat_ids:
            logger.warning("Telegram configuration missing. Skipping alert.")
            return

        report = data.get("ai_report") or {}
        symbol = html.escape(str(data.get("symbol", "N/A")))
        headline = html.escape(str(report.get("headline", data.get("desc", ""))))
        # summary = html.escape(str(report.get("summary", ""))) # Can be used if long form needed
        key_insight = html.escape(str(report.get("key_insight", "N/A")))
        
        source = html.escape(str(data.get("source", "N/A")))
        url = data.get("url")
        if source == "NSE" and url and not url.startswith("http"):
            url = f"https://nsearchives.nseindia.com/corporate/{url}"

        # Trade Quality & Emojis
        probability = data.get("probability", 0)
        quality_raw = data.get("trade_quality", "AVOID").upper()
        impact_score = data.get("impact_score", "N/A")
        expected_move = html.escape(str(report.get("expected_move", "N/A")))
        sentiment = html.escape(str(data.get("sentiment", "Neutral")))

        # Dynamic Header Icon & Emojis
        if "HIGH CONFIDENCE" in quality_raw: 
            header_icon = "🚨"
        elif "GOOD" in quality_raw: 
            header_icon = "✅"
        elif "POSSIBLE" in quality_raw: 
            header_icon = "⚠️"
        else:
            header_icon = "❌"

        # Message Format V7.5 (Probability Engine - Summary Added)
        message = (
            f"{header_icon} <b>{symbol.upper()}</b>\n"
            f"<b>News:</b> {headline}\n\n"
            f"<b>Summary:</b> <i>{report.get('summary', 'N/A')}</i>\n\n"
            f"<b>Sentiment:</b> {sentiment}\n"
            f"<b>Impact:</b> {impact_score}/10\n"
            f"<b>Probability:</b> {probability}% (Intraday)\n"
            f"<b>Trade Quality:</b> {quality_raw}\n\n"
            f"<i>Source: {source}</i> | <a href='{url or '#'}'>Read Source</a>"
        )

        success = False
        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }

            try:
                # Use send_alert logging logic
                logger.debug(f"Sending alert to chat_id: {chat_id}")
                r = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
                if r.status_code != 200:
                   logger.error(f"Telegram Alert Error ({r.status_code}) for {chat_id}: {r.text}")
                r.raise_for_status()
                success = True
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
            
        if success:
            logger.info(f"Broadcasted alert for {symbol} ({source}) to recipients.")
        return success
