import pytz
import asyncio
import os
import logging
import inspect
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
        # self.bulk_source = BulkDealSource() # v5.2.4: Disabled Bulk system

    async def generate_morning_report(self):
        """v4.0: Instrumented Generation with Observability (Async)."""
        tz = pytz.timezone('Asia/Kolkata')
        now = datetime.now(tz)
        lookback = 66 if now.weekday() == 0 else 18
        
        try:
            report = await self.build_pre_market_report(hours=lookback)
            if len(report) > 50:
                send_result = self.bot.send_report(report)
                if inspect.isawaitable(send_result):
                    await send_result
                logger.info(f"Morning Report Sent (Lookback: {lookback}h)")
                return True
            else:
                logger.warning(f"Morning Report too short (len: {len(report)}). Skipping send.")
                return False
        except Exception as e:
            err_msg = f"[ERROR] <b>Report Builder Failure</b>: {str(e)[:100]}"
            logger.error(f"FATAL: Report Generation Failed: {e}", exc_info=True)
            # v4.0: Alert admin on failure
            try:
                alert_result = self.bot._send_raw(os.getenv("TELEGRAM_ADMIN_CHAT_ID"), err_msg)
                if inspect.isawaitable(alert_result):
                    await alert_result
            except: pass
            return False

    async def build_pre_market_report(self, hours=18):
        """v4.0: Analyzed Context Only Mode (Async)."""
        # Fetch only processed/analyzed high-impact items
        all_news = self.db.get_recent_analyzed_news(hours=hours, min_score=1)
        global_intel = await self.global_source.fetch_indices()
        # bulk_intel = await self.bulk_source.get_deals_for_report() # v5.2.4: Disabled
        
        # v2.0: AI Summarization using async LLM processor
        ai_res = {}
        llm_called = False
        if all_news:
            ai_res = await self.llm_processor.summarize_morning_batch(all_news)
            llm_called = True
        
        logger.info(f"Report Context: {len(all_news)} items | LLM Called: {llm_called}")

        report = ["<b>NSE PULSE: MORNING INTEL</b>"]
        report.append("------------------------")
        
        # 1. Global Setup (Rule #19)
        report.append("<b>GLOBAL SETUP</b>")
        report.append(f"- GIFT Nifty: {global_intel.get('GIFT Nifty', 'N/A')}")
        report.append(f"- Dow Jones: {global_intel.get('Dow Jones', 'N/A')}")
        report.append(f"- Nasdaq: {global_intel.get('Nasdaq', 'N/A')}")
        
        # 2. Executive Summary
        report.append(f"\n<b>STRATEGIST VIEW: {ai_res.get('theme', 'Market Update')}</b>")
        report.append(f"<i>{ai_res.get('summary', 'No significant news detected.')}</i>")
        report.append(f"<b>Sentiment:</b> {ai_res.get('sentiment', 'Neutral')}")
        
        # 3. High Impact Signals (v4.0 Null-Safe Sort)
        report.append("\n<b>INSTITUTIONAL TRIGGERS</b>")
        
        # Filter out impact_score=0 as per Rule #3 policy
        trigger_news = [n for n in all_news if int(n.get("impact_score") or 0) > 0]
        sorted_news = sorted(trigger_news, key=lambda x: int(x.get('impact_score') or 0), reverse=True)[:5]
        
        for idx, item in enumerate(sorted_news, 1):
            url = item.get('url', '#')
            if not url.startswith('http'): url = f"https://nsearchives.nseindia.com/corporate/{url}"
            report.append(f"<b>{idx}. {item['headline']}</b>")
            report.append(f"-> <a href='{url}'>Reference Filing</a>")

        # 4. Bulk & Block Deals (v5.2.4: Removed section to focus on filings)
        # ... (Removed per user request)

        report.append("\n------------------------")
        report.append("<i>Strict NSE filings only | Non-SEBI Adv.</i>")
        
        return "\n".join(report)

