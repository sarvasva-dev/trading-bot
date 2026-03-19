import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ReportBuilder:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def generate_morning_report(self):
        """Generates and sends the morning report."""
        try:
            # Dynamic Time Calculation:
            # If Monday (0), look back to Friday 15:30 (approx 66 hours)
            # Else, look back to Yesterday 15:30 (approx 18 hours)
            is_monday = datetime.now().weekday() == 0
            lookback_hours = 66 if is_monday else 18
            
            logger.info(f"Generating Pre-Market Report (Lookback: {lookback_hours} hours)...")
            
            report_text = self.build_pre_market_report(hours=lookback_hours)
            if report_text and len(report_text) > 50:
                 self.bot.send_report(report_text)
            else:
                 logger.info("Morning report empty, skipping send.")
        except Exception as e:
            logger.error(f"Failed to generate morning report: {e}")

    def build_pre_market_report(self, hours=18):
        """Builds a v7.0 Architect-spec pre-market intelligence report."""
        logger.info(f"Building v7.0 Pre-Market Intelligence Report (Last {hours} hours)...")
        
        report = [f"<b>🌅 PRE-MARKET INTELLIGENCE REPORT ({datetime.now().strftime('%d %b')})</b>\n"]
        report.append("<i>News tracked since last Market Close</i>\n")
        
        # Section 1: Global Events
        global_news = [item for item in self.db.get_latest_news(min_impact=50, hours=hours) 
                       if "global" in item[0].lower() or "us" in item[0].lower() or "fed" in item[0].lower()]
        self._add_section(report, "Global Events 🌎", global_news[:3])
        
        # Section 2: Major Indian News
        indian_news = self.db.get_latest_news(min_impact=70, hours=hours)
        # Filter out those already in global if overlapping
        self._add_section(report, "Major Indian News 🇮🇳", indian_news[:3])
        
        # Section 3: Corporate Announcements
        corp_news = self.db.get_latest_news(perspective="ANNOUNCEMENT", min_impact=40, hours=hours)
        self._add_section(report, "Corporate Announcements 📢", corp_news[:3])
        
        # Section 4: Market Risks
        risks = self.db.get_latest_news(sentiment="Bearish", min_impact=70, hours=hours)
        self._add_section(report, "Market Risks 🔻", risks[:3])
        
        # Section 5: Opportunities
        opps = self.db.get_latest_news(sentiment="Bullish", min_impact=70, hours=hours)
        self._add_section(report, "Opportunities 🔼", opps[:3])
        
        return "\n".join(report)

    def _add_section(self, report, title, items):
        if not items:
            return
        report.append(f"<b>{title}</b>")
        for headline, summary, source, url, impact in items:
            # v7.0 uses concise bullet format with Impact Score
            report.append(f"• <a href='{url}'>{headline}</a> ({source} | Impact: {impact}/10)")
        report.append("") # Spacer
