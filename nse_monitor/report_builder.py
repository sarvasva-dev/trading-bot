import logging
import pytz
from datetime import datetime
from nse_monitor.config import BOT_NAME

logger = logging.getLogger(__name__)

class ReportBuilder:
    def __init__(self, bot, db, llm_processor):
        self.bot = bot
        self.db = db
        self.llm_processor = llm_processor

    def generate_morning_report(self):
        """Generates and sends the morning report."""
        try:
            # Dynamic Time Calculation:
            # If Monday (0), look back to Friday 15:30 (approx 66 hours)
            # Else, look back to Yesterday 15:30 (approx 18 hours)
            tz = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(tz)
            is_monday = now_ist.weekday() == 0
            lookback_hours = 66 if is_monday else 18
            
            logger.info(f"Generating {BOT_NAME} Morning Report (Lookback: {lookback_hours} hours)...")
            
            report_text = self.build_pre_market_report(hours=lookback_hours)
            if report_text and len(report_text) > 50:
                 self.bot.send_report(report_text)
            else:
                 logger.info("Morning report empty, skipping send.")
        except Exception as e:
            logger.error(f"Failed to generate morning report: {e}")

    def build_pre_market_report(self, hours=18):
        """Builds a v7.5 execution-spec pre-market intelligence report with AI Batching."""
        logger.info(f"Building {BOT_NAME} Pre-Market Intelligence Report (Last {hours} hours)...")
        
        # 1. Fetch All Analyzed News for the Recap
        all_news = self.db.get_latest_news(min_impact=4, hours=hours) # Fetch all relevant news
        
        # 2. Generate Master AI Summary if news exists
        ai_summary_text = ""
        if all_news:
             ai_res = self.llm_processor.summarize_morning_batch(all_news)
             if ai_res:
                 ai_summary_text = (
                     f"🧠 <b>EXECUTIVE PREVIEW: {ai_res.get('theme', 'Market Update')}</b>\n"
                     f"<i>{ai_res.get('summary', '')}</i>\n\n"
                     f"🎯 <b>Sectors to watch:</b> {ai_res.get('sectors_to_watch', 'All')}\n"
                     f"📊 <b>Sentiment:</b> {ai_res.get('sentiment', 'Neutral')}\n\n"
                     f"---"
                 )

        report = [f"<b>🌅 {BOT_NAME.upper()} MORNING INTEL ({datetime.now().strftime('%d %b')})</b>\n"]
        if ai_summary_text:
            report.append(ai_summary_text)
        
        report.append("<i>Individual High-Impact Events:</i>\n")
        
        # Section 1: Global Events
        global_news = [item for item in self.db.get_latest_news(min_impact=5, hours=hours) 
                       if any(kw in item[0].lower() for kw in ["global", "us", "fed", "nasdaq", "dow", "nikkei", "inflation", "oil", "crude"])]
        self._add_section(report, "Global Cues 🌎", global_news[:3])
        
        # Section 2: Major Indian News
        indian_news = self.db.get_latest_news(min_impact=7, hours=hours)
        self._add_section(report, "Market Moving News 🇮🇳", indian_news[:3])
        
        # Section 3: Corporate Announcements
        corp_news = self.db.get_latest_news(perspective="ANNOUNCEMENT", min_impact=4, hours=hours)
        self._add_section(report, "Corporate Filings 📢", corp_news[:3])
        
        # Section 4: Risks & Opportunities
        risks = self.db.get_latest_news(sentiment="Bearish", min_impact=6, hours=hours)
        self._add_section(report, "Risk factors 🔻", risks[:3])
        
        opps = self.db.get_latest_news(sentiment="Bullish", min_impact=6, hours=hours)
        self._add_section(report, "Potential Upside 🔼", opps[:3])
        
        return "\n".join(report)

    def _add_section(self, report, title, items):
        if not items:
            return
        report.append(f"<b>{title}</b>")
        for headline, summary, source, url, impact in items:
            # Concise bullet format with 1-10 Impact Score
            report.append(f"• <a href='{url}'>{headline}</a> ({source} | Impact: {impact}/10)")
        report.append("") # Spacer
