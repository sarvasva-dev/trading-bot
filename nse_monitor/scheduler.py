import logging
import pytz
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

class MarketScheduler:
    def __init__(self, system):
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone('Asia/Kolkata'))
        self.system = system

    async def safe_run_cycle(self):
        """Wraps the intelligence cycle in crash protection (Async)."""
        try:
            await self.system.run_cycle()
        except Exception as e:
            logger.error(f"Cycle failure: {e}")

    async def start(self):
        """Initializes and starts the market intelligence schedule (Async)."""
        from nse_monitor.config import DISABLE_SCHEDULER
        if DISABLE_SCHEDULER:
            logger.warning("SCHEDULER IS DISABLED via config. Standby mode.")
            while True:
                await asyncio.sleep(3600)
            return

        logger.info("Initializing Market Pulse Schedule (v2.0 Async)...")
        
        # 1. 3-Minute Intelligence Cycle
        self.scheduler.add_job(
            self.safe_run_cycle,
            'interval',
            minutes=3,
            id='market_intel_cycle'
        )

        # 2. Daily Pre-Market Multi-Source Report (08:30 IST)
        self.scheduler.add_job(
            self.system.report_builder.generate_morning_report,
            'cron',
            day_of_week='mon-fri',
            hour=8,
            minute=30,
            id='pre_market_report'
        )

        # 3. Weekly Memory Flush (Sun 02:00)
        import os
        self.scheduler.add_job(
            lambda: os._exit(0),
            'cron',
            day_of_week='sun',
            hour=2,
            minute=0,
            id='weekly_memory_flush'
        )

        # 4. Auto-Verify Payments (Every 5 minutes)
        self.scheduler.add_job(
            self.system.check_pending_payments,
            'interval',
            minutes=5,
            id='payment_polling'
        )

        # 5. Daily Maintenance (00:01 IST)
        self.scheduler.add_job(
            self.system.daily_maintenance,
            'cron',
            hour=0,
            minute=1,
            id='daily_system_maintenance'
        )
        
        # 6. Post-Market Billing (16:00 IST)
        self.scheduler.add_job(
            self.system.eod_billing,
            'cron',
            hour=16,
            minute=0,
            id='eod_billing_deduction'
        )

        logger.info("Scheduler configured: 08:30 Reports | 00:01 Maintenance | 3-Min Polling.")
        self.scheduler.start()

    async def send_pre_market_report(self):
        """Builds and broadcasts the consolidated intelligence report (Async)."""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        logger.info(f"Generating Pre-Market Intelligence Report (Day: {now.strftime('%A')})")
        
        try:
            is_monday = now.weekday() == 0
            hours_to_fetch = 64 if is_monday else 18
            
            report_text = await self.system.report_builder.build_pre_market_report(hours=hours_to_fetch)
            
            if is_monday:
                report_text = "📅 **WEEKEND MARKET INTELLIGENCE RECAP**\n" + report_text
            
            await self.system.bot.send_report(report_text)
        except Exception as e:
            logger.error(f"Failed to generate daily report: {e}")
