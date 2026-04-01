import requests
import logging
from nse_monitor.config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    v2.0: Replaces EmailNotifier.
    Sends critical system failure alerts and heartbeats to the Admin via Telegram.
    """
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.admin_id = TELEGRAM_ADMIN_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def _repair_mojibake_text(self, value):
        if not isinstance(value, str) or not value:
            return value
        markers = ("Ã", "Â", "â", "ðŸ", "ï¸")
        repaired = value
        for _ in range(2):
            if not any(marker in repaired for marker in markers):
                break
            try:
                candidate = repaired.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if not candidate or candidate == repaired:
                break
            repaired = candidate
        return repaired

    def send_failure_alert(self, subject, error_message):
        """Sends a critical alert directly to the admin."""
        if not self.token or not self.admin_id:
            logger.warning("Telegram Notifier: Token or Admin ID missing. Alert suppressed.")
            return

        text = (
            f"🚨 <b>SYSTEM CRITICAL ERROR</b>\n"
            f"────────────────────────\n"
            f"<b>Subject:</b> {subject}\n"
            f"<b>Error:</b> <code>{error_message}</code>\n\n"
            f"📅 <i>Pls check server logs immediately.</i>"
        )
        
        try:
            payload = {
                "chat_id": self.admin_id,
                "text": self._repair_mojibake_text(text),
                "parse_mode": "HTML"
            }
            requests.post(self.base_url, json=payload, timeout=10)
            logger.info(f"✅ Failure alert sent to Admin Telegram ({self.admin_id}).")
        except Exception as e:
            logger.error(f"❌ Failed to send Telegram alert: {e}")

    def send_status_update(self, status_msg):
        """Sends a system status update directly to the Admin (v1.3)."""
        if not self.token or not self.admin_id: return
        
        try:
            payload = {
                "chat_id": self.admin_id,
                "text": self._repair_mojibake_text(status_msg),
                "parse_mode": "HTML"
            }
            # Use a slightly longer timeout for reliability
            requests.post(self.base_url, json=payload, timeout=15)
        except Exception as e:
            logger.error(f"❌ Failed to send status update: {e}")
