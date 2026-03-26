import logging
import pytz
from datetime import datetime
from nse_monitor.sources.global_source import GlobalSource
from nse_monitor.sources.bulk_deal_source import BulkDealSource

logger = logging.getLogger(__name__)

class ReportBuilder:
    def __init__(self, bot, db, llm_processor):
        self.bot = bot
        self.db = db
        self.llm_processor = llm_processor
        self.global_source = GlobalSource()
        self.bulk_source = BulkDealSource()

    def generate_morning_report(self):
        """Generates and sends the morning report."""
        try:
            tz = pytz.timezone('Asia/Kolkata')
            now = datetime.now(tz)
            lookback = 66 if now.weekday() == 0 else 18
            
            report = self.build_pre_market_report(hours=lookback)
            if len(report) > 50:
                self.bot.send_report(report)
        except Exception as e:
            logger.error(f"Report Generation Failed: {e}")

    def build_pre_market_report(self, hours=18):
        """Unified v7.5 Morning Intelligence Report."""
        all_news = self.db.get_recent_news(hours=hours)
        global_intel = self.global_source.fetch_indices()
        
        ai_res = self.llm_processor.summarize_morning_batch(all_news) if all_news else {}

        report = [f"🌅 <b>NSE PULSE: MORNING INTEL</b>"]
        report.append(f"────────────────────────")
        
        # 1. Global Setup (Rule #19)
        report.append(f"🌎 <b>GLOBAL SETUP</b>")
        report.append(f"• GIFT Nifty: {global_intel.get('GIFT Nifty', 'N/A')}")
        report.append(f"• Dow Jones: {global_intel.get('Dow Jones', 'N/A')}")
        
        # 2. Executive Summary
        report.append(f"\n🧠 <b>STRATEGIST VIEW: {ai_res.get('theme', 'Market Update')}</b>")
        report.append(f"<i>{ai_res.get('summary', 'No significant news detected.')}</i>")
        report.append(f"📊 <b>Sentiment:</b> {ai_res.get('sentiment', 'Neutral')}")
        
        # 3. High Impact Signals
        report.append(f"\n🚨 <b>INSTITUTIONAL TRIGGERS</b>")
        sorted_news = sorted(all_news, key=lambda x: x.get('impact_score', 0), reverse=True)[:5]
        for idx, item in enumerate(sorted_news, 1):
            url = item.get('url', '#')
            if not url.startswith('http'): url = f"https://nsearchives.nseindia.com/corporate/{url}"
            report.append(f"<b>{idx}. {item['headline']}</b>")
            report.append(f"👉 <a href='{url}'>Reference Filing</a>")

        # 4. Bulk Deals
        report.append(f"\n📊 <b>RECENT BULK DEALS</b>")
        report.append("<i>Coming soon from Moneycontrol stats...</i>")
        
        report.append(f"\n────────────────────────")
        report.append(f"📍 <i>Strict NSE filings only | Non-SEBI Adv.</i>")
        
        return "\n".join(report)

    # _add_section_v2 is no longer needed but kept for compatibility if referenced elsewhere
    def _add_section_v2(self, report, title, items):
        pass
