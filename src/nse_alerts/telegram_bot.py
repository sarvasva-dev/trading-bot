import logging
from typing import Optional

import requests

from .models import ProcessedAlert


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session = requests.Session()

    def send_alert(self, alert: ProcessedAlert) -> Optional[dict]:
        message = self._format_message(alert)
        
        if not self.token or not self.chat_id:
            logging.info("Telegram credentials missing, printing alert instead:\n%s", message)
            return None

        payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            resp = self.session.post(f"{self.base_url}/sendMessage", data=payload, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to send Telegram message", extra={"err": str(exc)})
            return None

    @staticmethod
    def _format_message(alert: ProcessedAlert) -> str:
        pdf_line = f"\nPDF: {alert.pdf_url}" if alert.pdf_url else ""
        symbol_line = f" ({alert.symbol})" if alert.symbol else ""
        return (
            "🚨 Market Alert\n\n"
            f"Company: {alert.company}{symbol_line}\n"
            f"News: {alert.headline}\n"
            f"Impact: {alert.impact}\n"
            f"Confidence: {alert.confidence}\n"
            f"Summary: {alert.summary}\n"
            f"Time: {alert.time.strftime('%d-%b-%Y %H:%M IST')}\n"
            "Source: NSE Announcement"
            f"{pdf_line}"
        )
