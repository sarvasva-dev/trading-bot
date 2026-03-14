import requests
import logging
from nse_monitor.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_alert(self, data, source_link=None):
        """Sends a formatted message to Telegram."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram configuration missing. Alert not sent.")
            return

        # Merging AI report with raw data
        report = data.get("ai_report") or {}
        company = report.get("company") or data.get("symbol")
        headline = report.get("headline") or data.get("desc")[:100]
        summary = report.get("summary") or data.get("desc")
        impact = report.get("impact", "Neutral")
        quantum = report.get("quantum", "N/A")
        duration = report.get("duration", "N/A")
        confidence = report.get("confidence", "N/A")
        key_insight = report.get("key_insight", "N/A")
        
        pdf_url = data.get("pdf_url")
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = f"https://nsearchives.nseindia.com/corporate/{pdf_url}"

        impact_emoji = {
            "Bullish": "🚀 Bullish",
            "Bearish": "📉 Bearish",
            "Neutral": "⚖️ Neutral"
        }.get(impact, "⚖️ Neutral")

        message = (
            f"🏢 <b>{company}</b>\n"
            f"📢 <b>{headline}</b>\n\n"
            f"📝 <b>Summary:</b> {summary}\n\n"
            f"💡 <b>Key Insight:</b> <i>{key_insight}</i>\n\n"
            f"📊 <b>Sentiment:</b> {impact_emoji}\n"
            f"⚡ <b>Quantum:</b> {quantum} Impact\n"
            f"🕒 <b>Duration:</b> {duration}\n"
            f"🎯 <b>Confidence:</b> {confidence}\n\n"
            f"🔗 <a href='{pdf_url or '#'}'>View Original PDF Announcement</a>"
        )

        params = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            logger.info(f"Sending Telegram alert for {company}...")
            response = requests.post(self.api_url, json=params, timeout=15)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False

if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    bot = TelegramBot()
    # bot.send_alert({"company": "Test", "headline": "Test News", "summary": "Info", "impact": "Bullish", "confidence": "0.9"})
