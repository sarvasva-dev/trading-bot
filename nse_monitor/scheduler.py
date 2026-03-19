import logging
import pytz
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

logger = logging.getLogger(__name__)

class MarketScheduler:
    def __init__(self, system):
        self.scheduler = BlockingScheduler(timezone=pytz.timezone('Asia/Kolkata'))
        self.system = system

    def safe_run_cycle(self):
        """Wraps the intelligence cycle in crash protection."""
        try:
            self.system.run_cycle()
        except Exception as e:
            logger.error(f"Cycle failure: {e}")

    def start(self):
        """Initializes and starts the market intelligence schedule."""
        from nse_monitor.config import DISABLE_SCHEDULER
        if DISABLE_SCHEDULER:
            logger.warning("SCHEDULER IS DISABLED via config. Entering minimal standby mode (Infinite Idle).")
            import time
            while True:
                time.sleep(3600)
            return

        logger.info("Initializing Market Pulse Schedule (v1.0)...")
        
        # 1. 3-Minute Intelligence Cycle (Standardized)
        self.scheduler.add_job(
            self.safe_run_cycle,
            'interval',
            minutes=3,
            id='market_intel_cycle'
        )

        # 2. Daily Pre-Market Multi-Source Report (08:30 IST, Mon-Fri)
        # Now uses the new AI Batch Summarization logic
        self.scheduler.add_job(
            self.system.report_builder.generate_morning_report,
            'cron',
            day_of_week='mon-fri',
            hour=8,
            minute=30,
            id='pre_market_report'
        )

        # 3. Dynamic User Update Handling (Every 1 minute)
        self.scheduler.add_job(
            self.system.bot.handle_updates,
            'interval',
            minutes=1,
            id='telegram_updates'
        )

        logger.info("Scheduler started (08:30 IST Reports | 3-Min Polling).")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler shutting down...")

    def send_pre_market_report(self):
        """Builds and broadcasts the consolidated intelligence report."""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        logger.info(f"Generating Pre-Market Intelligence Report (Day: {now.strftime('%A')})")
        
        try:
            # Monday Special: Aggregate all weekend news (last 64 hours)
            # Tue-Fri: Aggregate last 18 hours
            is_monday = now.weekday() == 0
            hours_to_fetch = 64 if is_monday else 18
            
            report_text = self.system.report_builder.build_pre_market_report(hours=hours_to_fetch)
            
            if is_monday:
                report_text = "📅 **WEEKEND MARKET INTELLIGENCE RECAP**\n" + report_text
            
            self.system.bot.send_report(report_text)
        except Exception as e:
            logger.error(f"Failed to generate daily report: {e}")
