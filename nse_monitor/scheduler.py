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

        logger.info("Initializing Intelligence Schedule (v7.5)...")
        
        # 1. High-Frequency Intelligence Cycle (Now handled in main.py loop)
        # We keep this for compatibility if scheduler is used as entry point
        self.scheduler.add_job(
            self.safe_run_cycle,
            'interval',
            minutes=2,
            id='market_intel_cycle'
        )

        # 2. Daily Pre-Market Multi-Source Report (08:30 IST, Mon-Fri)
        self.scheduler.add_job(
            self.send_pre_market_report,
            'cron',
            day_of_week='mon-fri',
            hour=8,
            minute=30,
            id='pre_market_report'
        )

        logger.info("Scheduler started with 08:30 reports.")
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
