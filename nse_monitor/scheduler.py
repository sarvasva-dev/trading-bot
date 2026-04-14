import logging
import pytz
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from nse_monitor.trading_calendar import TradingCalendar, NSE_HOLIDAYS

logger = logging.getLogger(__name__)

class MarketScheduler:
    def __init__(self, system):
        self.scheduler = AsyncIOScheduler(
            timezone=pytz.timezone('Asia/Kolkata'),
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 1800},
        )
        self.system = system

    async def _ensure_calendar_is_fresh(self):
        """Refresh holiday file when current year is missing, to avoid wrong trading-day decisions."""
        year = str(datetime.now(pytz.timezone('Asia/Kolkata')).year)
        if any(day.startswith(f"{year}-") for day in NSE_HOLIDAYS):
            return
        logger.warning("Trading calendar for %s missing in local cache. Attempting NSE sync.", year)
        try:
            await asyncio.to_thread(TradingCalendar.sync_from_nse)
        except Exception as e:
            logger.error("Trading calendar sync failed: %s", e)

    async def _run_pre_market_report(self):
        """Run scheduled morning report exactly once per day in DB state."""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        report_day = now.strftime("%Y-%m-%d")
        if self.system.db.get_config("last_pre_market_report_date", "") == report_day:
            logger.info("Pre-market report already sent for %s. Skipping duplicate.", report_day)
            return

        sent = await self.system.report_builder.generate_morning_report()
        if sent:
            self.system.db.set_config("last_pre_market_report_date", report_day)

    async def _run_morning_signal_dispatch(self):
        """Dispatches individually queued signals at 08:30 AM (v5.0)."""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        if not TradingCalendar.is_trading_day(now):
            return
            
        logger.info("Morning Dispatch Job: Starting individual signal broadcast.")
        await self.system.send_queued_signals()

    async def _maybe_send_startup_catchup_report(self):
        """If bot starts after 08:30 but before market open, send report immediately."""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        if not TradingCalendar.is_trading_day(now):
            return
        minutes_now = now.hour * 60 + now.minute
        if not (510 <= minutes_now < 555):  # 08:30 inclusive to 09:15 exclusive
            return

        report_day = now.strftime("%Y-%m-%d")
        if self.system.db.get_config("last_pre_market_report_date", "") == report_day:
            return

        logger.warning("Startup catch-up: dispatching delayed pre-market reports AND signals for %s.", report_day)
        await self._run_morning_signal_dispatch() # v5.1 Fix
        await self._run_pre_market_report()


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

        logger.info("Initializing Bulkbeat TV Schedule (v2.0 Async)...")
        await self._ensure_calendar_is_fresh()
        
        # 1. 3-Minute Intelligence Cycle
        self.scheduler.add_job(
            self.safe_run_cycle,
            'interval',
            minutes=3,
            id='market_intel_cycle'
        )

        # 2. Daily Pre-Market Multi-Source Report (08:30 IST)
        self.scheduler.add_job(
            self._run_pre_market_report,
            'cron',
            day_of_week='mon-fri',
            hour=8,
            minute=30,
            id='pre_market_report'
        )

        # 3. Daily Memory Flush (04:00 IST)
        import os
        self.scheduler.add_job(
            lambda: os._exit(0),
            'cron',
            hour=4,
            minute=0,
            id='daily_memory_flush'
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

        # 7. Weekly holiday sync (Sun 03:00 IST)
        self.scheduler.add_job(
            self._ensure_calendar_is_fresh,
            'cron',
            day_of_week='sun',
            hour=3,
            minute=0,
            id='holiday_sync'
        )

        logger.info("Scheduler configured: 08:30 Reports | 00:01 Maintenance | 3-Min Polling.")
        
        # 8. Morning Signal Dispatch (08:30 IST)
        # We run this alongside the report to ensure all intel hits at once
        self.scheduler.add_job(
            self._run_morning_signal_dispatch,
            'cron',
            day_of_week='mon-fri',
            hour=8,
            minute=30,
            id='morning_signal_dispatch'
        )

        self.scheduler.start()
        await self._maybe_send_startup_catchup_report()

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
