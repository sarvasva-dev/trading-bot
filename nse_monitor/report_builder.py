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
        self.bulk_source = BulkDealSource()

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
                logger.info(f"âœ… Morning Report Sent (Lookback: {lookback}h)")
            else:
                logger.warning(f"âš ï¸ Morning Report too short (len: {len(report)}). Skipping send.")
        except Exception as e:
            err_msg = f"âŒ <b>Report Builder Failure</b>: {str(e)[:100]}"
            logger.error(f"FATAL: Report Generation Failed: {e}", exc_info=True)
            # v4.0: Alert admin on failure
            try:
                alert_result = self.bot._send_raw(os.getenv("TELEGRAM_ADMIN_CHAT_ID"), err_msg)
                if inspect.isawaitable(alert_result):
                    await alert_result
            except: pass

    async def build_pre_market_report(self, hours=18):
        """v4.0: Analyzed Context Only Mode (Async)."""
        # Fetch only processed/analyzed high-impact items
        all_news = self.db.get_recent_analyzed_news(hours=hours, min_score=1)
        global_intel = await self.global_source.fetch_indices()
        bulk_intel = await self.bulk_source.get_deals_for_report()
        
        # v2.0: AI Summarization using async LLM processor
        ai_res = {}
        llm_called = False
        if all_news:
            ai_res = await self.llm_processor.summarize_morning_batch(all_news)
            llm_called = True
        
        logger.info(f"Report Context: {len(all_news)} items | LLM Called: {llm_called}")

        report = [f"ðŸŒ… <b>NSE PULSE: MORNING INTEL</b>"]
        report.append(f"â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
        
        # 1. Global Setup (Rule #19)
        report.append(f"ðŸŒŽ <b>GLOBAL SETUP</b>")
        report.append(f"â€¢ GIFT Nifty: {global_intel.get('GIFT Nifty', 'N/A')}")
        report.append(f"â€¢ Dow Jones: {global_intel.get('Dow Jones', 'N/A')}")
        report.append(f"â€¢ Nasdaq: {global_intel.get('Nasdaq', 'N/A')}")
        
        # 2. Executive Summary
        report.append(f"\nðŸ§  <b>STRATEGIST VIEW: {ai_res.get('theme', 'Market Update')}</b>")
        report.append(f"<i>{ai_res.get('summary', 'No significant news detected.')}</i>")
        report.append(f"ðŸ“Š <b>Sentiment:</b> {ai_res.get('sentiment', 'Neutral')}")
        
        # 3. High Impact Signals (v4.0 Null-Safe Sort)
        report.append(f"\nðŸš¨ <b>INSTITUTIONAL TRIGGERS</b>")
        
        # Filter out impact_score=0 as per Rule #3 policy
        trigger_news = [n for n in all_news if int(n.get("impact_score") or 0) > 0]
        sorted_news = sorted(trigger_news, key=lambda x: int(x.get('impact_score') or 0), reverse=True)[:5]
        
        for idx, item in enumerate(sorted_news, 1):
            url = item.get('url', '#')
            if not url.startswith('http'): url = f"https://nsearchives.nseindia.com/corporate/{url}"
            report.append(f"<b>{idx}. {item['headline']}</b>")
            report.append(f"ðŸ‘‰ <a href='{url}'>Reference Filing</a>")

        # 4. Bulk & Block Deals (v4.2.1: Truthful Recap)
        report.append(f"\nðŸ”„ <b>BULK & BLOCK DEALS</b>")
        
        from nse_monitor.config import KNOWN_INSTITUTIONS, BULK_REPORT_MIN_VAL_CR, BULK_MAX_ITEMS_REPORT
        
        deals_list = bulk_intel.get("deals", [])
        is_stale = bulk_intel.get("is_stale", True)
        recap_date = bulk_intel.get("recap_date", "N/A")
        
        if not is_stale and deals_list:
            report.append(f"<i>Recap Session: {recap_date}</i>")
            # Filter & Sort
            eligible = [d for d in deals_list if d.get("val_cr", 0) >= BULK_REPORT_MIN_VAL_CR]
            sorted_bulk = sorted(eligible, key=lambda x: (-x['val_cr'], x['symbol']))[:BULK_MAX_ITEMS_REPORT]
            
            if sorted_bulk:
                for d in sorted_bulk:
                    # v4.2.1: Hardened matching
                    clean_name = " ".join(d['client_name'].upper().split())
                    badge = "ðŸ› " if any(inst in clean_name for inst in KNOWN_INSTITUTIONS) else ""
                    bs_icon = "ðŸŸ¢" if d['buy_sell'] == "BUY" else "ðŸ”´"
                    report.append(f"â€¢ {badge}{d['symbol']}: {d['buy_sell']} {d['client_name']} | <b>â‚¹{d['val_cr']:.1f} Cr</b> {bs_icon}")
            else:
                report.append(f"<i>No significant deals (>â‚¹{BULK_REPORT_MIN_VAL_CR} Cr) detected.</i>")
        else:
            # Stale or Empty path
            expected_session = bulk_intel.get("recap_date", "N/A")
            report.append(f"<i>Session: {expected_session}</i>")
            report.append(f"âš ï¸ <i>No fresh deals detected for this session.</i>")

        report.append(f"\nâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
        report.append(f"ðŸ“ <i>Strict NSE filings only | Non-SEBI Adv.</i>")
        
        return "\n".join(report)

