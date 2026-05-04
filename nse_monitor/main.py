import asyncio
import atexit
import hashlib
import logging
import logging.handlers
import os
import random
import signal
import sys
import time
import warnings
import shutil
import glob
from datetime import datetime, timedelta
import inspect
import gc

import aiohttp
import pytz

from nse_monitor.config import (
    BOT_NAME,
    LOGS_DIR,
    PID_FILE_NAME,
    ROOT_DIR,
    LIVE_ALERT_START_MINUTES,
    LIVE_ALERT_END_MINUTES,
)
from nse_monitor.database import Database
from nse_monitor.impact_tracker import ImpactTracker
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.market_analyzer import MarketAnalyzer
from nse_monitor.nudge_manager import NudgeManager
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.report_builder import ReportBuilder
from nse_monitor.scheduler import MarketScheduler
# from nse_monitor.sources.bulk_deal_source import BulkDealSource
# from nse_monitor.sources.economic_times_source import EconomicTimesSource
# from nse_monitor.sources.moneycontrol_source import MoneycontrolSource
from nse_monitor.sources.nse_sme_source import NseSmeSource
from nse_monitor.sources.nse_source import NSESource
from nse_monitor.telegram_bot import TelegramBot
from nse_monitor.telegram_notifier import TelegramNotifier
from nse_monitor.trading_calendar import TradingCalendar
from nse_monitor.watchdog import BotWatchdog

# Suppress warnings
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def ist_time(*args):
    return datetime.now(pytz.timezone("Asia/Kolkata")).timetuple()


logging.Formatter.converter = ist_time
os.makedirs(LOGS_DIR, exist_ok=True)
_log_path = os.path.join(LOGS_DIR, "app.log")
_log_handler = logging.handlers.RotatingFileHandler(
    _log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
_log_handler.setFormatter(_formatter)
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_formatter)
logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _log_handler])
logger = logging.getLogger("BulkbeatTV")


def _pid_file_path():
    return os.path.abspath(os.path.join(ROOT_DIR, PID_FILE_NAME))


def _remove_pid_file(pid_file):
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception as exc:
        logger.warning("PID cleanup failed at %s: %s", pid_file, exc)


def check_single_instance():
    import psutil

    pid_file = _pid_file_path()
    logger.info("Instance lock path: %s", pid_file)

    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                logger.error("FATAL: Instance already running (PID %s).", old_pid)
                sys.exit(1)
            logger.warning("Stale PID file found for dead PID %s. Cleaning up.", old_pid)
            _remove_pid_file(pid_file)
        except Exception as exc:
            logger.warning("Unreadable/stale PID file. Cleaning up. Reason: %s", exc)
            _remove_pid_file(pid_file)

    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: _remove_pid_file(pid_file))


class MarketIntelligenceSystem:
    def __init__(self):
        logger.info("=" * 48)
        logger.info("  %s v3.0 - ASYNC OS BOOT", BOT_NAME)
        logger.info("=" * 48)

        self.ist = pytz.timezone("Asia/Kolkata")
        self.db = Database()

        async def notify_admin_on_ban(alert_text):
            if hasattr(self, "bot"):
                result = self.bot._send_raw(os.getenv("TELEGRAM_ADMIN_CHAT_ID"), alert_text)
                if inspect.isawaitable(result):
                    await result

        from nse_monitor.nse_api import NSEClient

        self.nse_client = NSEClient(on_403=notify_admin_on_ban)
        self.bot = TelegramBot(db=self.db, nse_client=self.nse_client)
        self.pdf_processor = PDFProcessor()
        self.llm_processor = LLMProcessor()
        self.report_builder = ReportBuilder(self.bot, self.db, self.llm_processor)
        self.analyzer = MarketAnalyzer(self.nse_client)
        self.impact_tracker = ImpactTracker(self.db, self.nse_client)
        self.nudge_manager = NudgeManager(self.db, self.bot)
        self.calendar = TradingCalendar()

        self.daily_alerts_count = 0
        self.last_budget_reset = None

        self.sources = [
            NSESource(client=self.nse_client),
            NseSmeSource(client=self.nse_client),
            # EconomicTimesSource(),   # Disabled — re-enable when needed
            # MoneycontrolSource(),    # Disabled — re-enable when needed
            # BulkDealSource(nse_client=self.nse_client),
        ]

        self.memory_lock = asyncio.Lock()
        # v3.1: Gates concurrent LLM calls; same 5-peak as before but non-blocking async wait
        self._llm_sem = asyncio.Semaphore(5)
        self.notifier = TelegramNotifier()
        self.health_session = None # v5.2: Pooled session for diagnostic checks
        self.watchdog = BotWatchdog(self.notifier, os.path.join(ROOT_DIR, "logs", "service.log"))
        self._queue_worker_task = None
        logger.info("================================================")
        logger.info("  Bulkbeat TV — The Pulse of Institutional Money")
        logger.info("  Market Intelligence Engine v3.0 ONLINE")
        logger.info("================================================")

    async def start_background_tasks(self):
        await self.bot.initialize()
        self.db.reset_inflight_news()
        asyncio.create_task(self.bot.handle_updates_loop())
        asyncio.create_task(self.run_auto_backup_task())
        self._queue_worker_task = asyncio.create_task(self.process_pending_queue_loop())
        self.watchdog.start()


    def is_market_hours(self):
        now = datetime.now(self.ist)
        if not TradingCalendar.is_trading_day(now):
            return False
        # Live signals are restricted to configured market session timings.
        curr_min = now.hour * 60 + now.minute
        return LIVE_ALERT_START_MINUTES <= curr_min < LIVE_ALERT_END_MINUTES

    async def process_pending_queue_loop(self):
        """Continuously process queued items so LLM + routing remain live."""
        logger.info("Queue Worker: started.")
        while True:
            try:
                processed = await self.process_pending_news_once(max_batches=4)
                await asyncio.sleep(0.2 if processed else 1.0)
            except Exception as e:
                logger.error("Queue Worker failure: %s", e)
                await asyncio.sleep(3)

    async def process_pending_news_once(self, max_batches=1):
        """Process bounded pending batches to preserve scrape cadence."""
        processed_total = 0
        for _ in range(max_batches):
            pending = self.db.claim_pending_news(limit=10)  # v3.1: 2x batch throughput
            if not pending:
                break
            analysis_tasks = [self._process_single_item(item) for item in pending]
            await asyncio.gather(*analysis_tasks, return_exceptions=True)
            processed_total += len(pending)
            await asyncio.sleep(0)
        return processed_total

    async def eod_billing(self):
        now = datetime.now(self.ist)
        if TradingCalendar.is_trading_day(now):
            logger.info("Post-market EOD: decrementing user credits.")
            self.db.decrement_working_days()
        else:
            logger.info("Skipping EOD credit deduction (holiday/weekend).")

    async def daily_maintenance(self):
        logger.info("Running midnight maintenance.")
        expired_users = self.db.get_expired_users()
        for chat_id in expired_users:
            try:
                send_result = self.bot._send_raw(chat_id, "Subscription expired. Please recharge to continue.")
                if inspect.isawaitable(send_result):
                    await send_result
            except Exception:
                continue
        self.db.run_maintenance()
        # v1.3.4: Delegating to the new high-trust backup rotation logic
        self.db.backup()

    async def run_auto_backup_task(self):
        """v2.0: Standalone background task to ensure daily snapshots (Requested)."""
        logger.info("Auto-Backup: Background task starting.")
        while True:
            try:
                # 1. Determine wait time until midnight IST
                now = datetime.now(self.ist)
                target = now.replace(hour=0, minute=5, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                
                wait_seconds = (target - now).total_seconds()
                logger.info(f"Auto-Backup: Next snapshot scheduled in {wait_seconds/3600:.1f} hours.")
                await asyncio.sleep(wait_seconds)
                
                # 2. Perform consistent online backup
                self.db.backup()
            except Exception as e:
                logger.error(f"Auto-Backup: Task error: {e}")
                await asyncio.sleep(600) # Retry after 10 mins on error

    async def check_pending_payments(self):
        pending = self.db.get_pending_payment_links()
        if not pending:
            return
        from nse_monitor.payment_processor import RazorpayProcessor
        from nse_monitor.config import SUBSCRIPTION_PLANS

        rp = RazorpayProcessor()
        loop = asyncio.get_running_loop()
        for row in pending:
            pl_id, chat_id, _days = row[0], row[1], row[2]
            plan_amount = int(row[3] or 0) if len(row) > 3 else 0
            payable_amount = int(row[4] or 0) if len(row) > 4 else 0
            discount_percent = int(row[5] or 0) if len(row) > 5 else 0
            days_added = await loop.run_in_executor(None, lambda id=pl_id: rp.verify_payment_status(id))
            if days_added:
                self.db.add_working_days(chat_id, days_added)
                self.db.update_payment_link_status(pl_id, "processed")

                # v8.0: Payment attribution + referral reward credit
                fallback_amount = next((int(k) for k, p in SUBSCRIPTION_PLANS.items() if p["days"] == days_added), 0)
                amount_paid = payable_amount or plan_amount or fallback_amount
                if amount_paid > 0:
                    self.db.record_first_payment(chat_id, amount_paid, pl_id)
                    self.db.credit_referral_reward_on_conversion(chat_id, amount_paid, pl_id)

                if discount_percent > 0:
                    self.db.clear_user_discount_percent(chat_id)

                send_result = self.bot._send_raw(chat_id, f"Payment success. {days_added} market days added.")
                if inspect.isawaitable(send_result):
                    await send_result

    async def send_queued_signals(self):
        """v5.1: High-integrity dispatch for overnight qualified news (status=3)."""
        now_dt = datetime.now(self.ist).date()
        
        # 1. Budget Reset (Mandatory for clean slate)
        if self.last_budget_reset != now_dt:
            logger.info(f"Morning Dispatch: Resetting daily alert budget (Old date: {self.last_budget_reset})")
            self.daily_alerts_count = 0
            self.last_budget_reset = now_dt
            self.db.clear_symbol_cooldowns()

        logger.info("Morning Dispatch: Scanning for Status=3 queued items...")
        queued_items = self.db.get_queued_news(hours=72)
        
        if not queued_items:
            logger.info("Morning Dispatch: Queue empty.")
            return

        logger.info(f"Morning Dispatch: Broadcasting {len(queued_items)} qualified signals.")
        
        for item in queued_items:
            news_id = item["id"]
            symbol = item["symbol"]
            score = item["impact_score"]
            sentiment = item["sentiment"]
            
            analysis = {
                "symbol": symbol,
                "impact_score": score,
                "sentiment": sentiment,
                "trigger": item.get("trigger", "N/A"),
                "sector": item.get("perspective", "N/A"),
                "valid_event": True
            }
            
            try:
                # Dispatch Signal
                send_result = self.bot.send_signal(item, analysis)
                if inspect.isawaitable(send_result):
                    await send_result
                
                # Register in system
                self.db.mark_alert_sent(news_id)
                self.db.mark_analysis_complete(
                    news_id, score, sentiment, 
                    trigger=item.get("trigger"), 
                    perspective=item.get("perspective"), 
                    alerted=True,
                    status=2
                )
                
                self.daily_alerts_count += 1
                self.db.set_symbol_cooldown(symbol, time.time())
                
                logger.info(f"Morning Dispatch: Sent {symbol} signal.")
                await asyncio.sleep(1.5) # Flood protection
                
            except Exception as e:
                logger.error(f"Morning Dispatch: Failed for {symbol}: {e}")

        logger.info("Morning Dispatch: Sequence completed.")

    async def health_check(self):
        """Pre-flight system validation with explicit Telegram network diagnostics."""
        logger.info("Running startup health checks...")

        # 1) Database check
        try:
            self.db.set_config("health_check_ping", str(time.time()))
            logger.info("Health: Database writable [OK]")
        except Exception as exc:
            logger.error("Health: Database writable [FAIL] (%s)", exc)
            return False

        # v5.2: Use Pooled Health Session to prevent RAM-bloat from one-off sessions
        if not self.health_session or self.health_session.closed:
            self.health_session = aiohttp.ClientSession()

        # 2) Telegram reachability check
        try:
            async with self.health_session.get("https://api.telegram.org", timeout=10) as resp:
                if resp.status != 200:
                    logger.error("Health: Telegram network degraded [WARN] (HTTP %s)", resp.status)
                else:
                    logger.info("Health: Telegram network reachable [OK]")
                await resp.release()
        except Exception as exc:
            logger.error("Health: Telegram network unreachable [FAIL] (%s)", exc)
            return False

        # 3) Telegram auth check
        try:
            url = f"{self.bot.base_url}/getMe"
            async with self.health_session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("Health: Telegram bot authentication [OK]")
                else:
                    logger.error("Health: Telegram auth failed [FAIL] (HTTP %s)", resp.status)
                    return False
                await resp.release()
        except Exception as exc:
            logger.error("Health: Telegram auth check [FAIL] (%s)", exc)
            return False

        # 4) AI key check
        if self.llm_processor.sarvam_key:
            logger.info("Health: AI intelligence key present [OK]")
        else:
            logger.error("Health: AI intelligence key missing [FAIL]")
            return False

        return True

    async def run_cycle(self):
        logger.info("Starting strict intelligence cycle.")
        self.watchdog.heartbeat()

        now = datetime.now(self.ist)
        today_date = now.date()
        if self.last_budget_reset != today_date:
            self.daily_alerts_count = 0
            self.last_budget_reset = today_date
            self.db.clear_symbol_cooldowns()
            logger.info("Daily budget and cooldown state reset.")

        # v6.4: Real-time Status Audit (Proof of Logic)
        media_mute = self.db.get_config("media_mute", "0")
        current_thresh = self.db.get_config("ai_threshold", "8")
        media_status = "MUTED (Official Only)" if media_mute == "1" else "ACTIVE"
        logger.info(">>> Intelligence Cycle Started | Threshold=%s | Media=%s", current_thresh, media_status)

        active_sources = list(self.sources)

        # Stagger NSE sources to avoid simultaneous requests to the same IP
        # NSE + NSE_SME fire together = ban risk. Add small jitter between them.
        source_results = []
        for i, source in enumerate(active_sources):
            if i > 0:
                await asyncio.sleep(random.uniform(1.5, 3.0))
            try:
                result = await source.fetch()
                source_results.append(result)
            except Exception as e:
                logger.error("Source %s failed: %s", source.NAME if hasattr(source, 'NAME') else i, e)
                source_results.append([])

        raw_items = []
        fetched_count = 0
        for items in source_results:
            if not items:
                continue
            raw_items.extend(items)
            fetched_count += len(items)

        if fetched_count == 0 and self.is_market_hours():
            logger.warning("Pipeline alert: zero news items fetched globally.")

        ingested = 0
        for item in raw_items:
            raw_id = item.get("raw_id", "")
            hash_in = f"{item.get('headline', '').lower()}|{item.get('symbol', 'N/A').upper()}|{raw_id}"
            content_hash = hashlib.sha256(hash_in.encode()).hexdigest()

            exists, _ = self.db.news_exists(item.get("url"), content_hash)
            # v5.3: Enhanced headline-based deduplication to prevent cross-source duplicates
            if not exists:
                if self.db.is_content_duplicate(item.get("headline"), content_hash, item.get("symbol")):
                    logger.debug("Semantic block: duplicate headline suppressed for %s", item.get('headline')[:50])
                    continue
                
                item["content_hash"] = content_hash
                if self.db.add_news_item(item):
                    ingested += 1

        # v3.1.1: Stale pruner ONLY during market hours (09:15-15:30)
        # Off-hours: overnight news process honi chahiye for 8:30 AM morning dispatch
        if self.is_market_hours():
            self.db.expire_stale_pending_news(max_age_hours=4)
        await self.nudge_manager.run_audit()
        logger.info("Pipeline: fetched=%s ingested=%s", fetched_count, ingested)

        # Keep scraping deterministic at 3-minute cadence; process one immediate batch.
        processed_this_cycle = await self.process_pending_news_once(max_batches=1)
        logger.info("Intelligence: analyzed=%s (immediate batch)", processed_this_cycle)
        gc.collect() # v5.2: Force RAM recovery after heavy processing
        return (ingested > 0) or (processed_this_cycle > 0)

    def _is_routine_news(self, headline, summary):
        """Pre-LLM Code Filter to reject routine NSE filings immediately (Rule #14 & others)."""
        text = (headline + " " + summary).lower()
        
        routine_keywords = [
            "regulation 74(5)", "regulation 40(9)", "compliance certificate",
            "annual report", "copy of newspaper publication", "published in newspaper",
            "audio recording of earnings call", "transcript of earnings call", 
            "audio recording", "transcript", "schedule of analyst", "analyst meeting",
            "intimation of book closure", "closure of trading window", "trading window",
            "loss of share certificate", "issue of duplicate share",
            "employee stock option", "esop",
            "appointment of independent director", "resignation of independent director",
            "postal ballot", "voting results", "change in registered office",
            "board meeting intimation", "intimation of board meeting",
            "secretarial compliance report", "reaffirmation of credit rating",
            "allotment of equity shares"
        ]
        
        safe_triggers = ["bonus", "dividend", "split", "buyback", "fund raising", "merger", "acquisition", "order", "deal"]

        for kw in routine_keywords:
            if kw in text:
                if ("board meeting" in kw or "analyst" in kw or "allotment" in kw) and any(safe in text for safe in safe_triggers):
                    continue
                return True, f"Routine keyword: '{kw}'"
        
        return False, ""

    async def _process_single_item(self, item):
        news_id = item["db_id"]
        from nse_monitor.config import ALERT_POLICY_MODE, ALLOWED_LIVE_SOURCES, DAILY_ALERT_HARD_CAP, NEUTRAL_BLOCK, SYMBOL_COOLDOWN_MIN

        pdf_path = None
        try:
            market_on = self.is_market_hours()
            if item.get("url") and ".pdf" in item["url"].lower():
                try:
                    loop = asyncio.get_event_loop()
                    pdf_path = await loop.run_in_executor(None, lambda: self.pdf_processor.download_pdf(item["url"]))
                    text = await loop.run_in_executor(None, lambda: self.pdf_processor.extract_text(pdf_path))
                    if text and len(text) > 100:
                        item["summary"] = item.get("summary", "") + f"\n[ENRICHMENT]: {text[500:2000]}"
                except Exception:
                    pass

            # --- PRE-LLM FILTER (Code-Based Rejection) ---
            is_junk, reason = self._is_routine_news(item.get("headline", ""), item.get("summary", ""))
            if is_junk:
                logger.info("Filtered (Pre-LLM): #%s %s - %s", news_id, item.get('symbol', 'N/A'), reason)
                self.db.mark_analysis_complete(news_id, 0, "Neutral", alerted=False)
                if pdf_path and os.path.exists(pdf_path):
                    try: os.remove(pdf_path)
                    except: pass
                return False
            # ---------------------------------------------

            # v3.1: Semaphore-gated LLM call (non-blocking async wait; 1GB RAM safe)
            async with self._llm_sem:
                analysis = await self.llm_processor.analyze_single_event(
                    [item], market_status="OPEN" if market_on else "CLOSED", source_name=item.get("source")
                )
            if not analysis:
                self.db.mark_analysis_complete(news_id, 0, "Neutral", alerted=False)
                return None

            score = int(analysis.get("impact_score", 0))
            # Fallback to item symbol if LLM fails
            symbol = str(analysis.get("symbol", item.get("symbol", "N/A"))).upper()
            sentiment = analysis.get("sentiment", "Neutral")

            if NEUTRAL_BLOCK and sentiment == "Neutral":
                logger.info("[BLOCKED: NEUTRAL] %s | Score: %s | Headline: %s", symbol, score, item.get('headline')[:50])
                self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
                return False

            # v5.3: Institutional Policy Enforcement (Recalibrated for Sensitivity)
            source_name = item.get("source", "").upper().strip()
            
            # v5.7: Dynamic Threshold Control from Admin Panel
            db_threshold = self.db.get_config("ai_threshold")
            try:
                min_score = int(db_threshold) if db_threshold else 8
            except (TypeError, ValueError):
                min_score = 8
            min_score = max(1, min(10, min_score))
            
            # v5.3: Institutional Policy Enforcement (Safety Floor)
            if ALERT_POLICY_MODE == "SENSITIVE_7PLUS" and min_score > 7:
                min_score = 7
            
            if score < min_score:
                logger.info("Filtered: #%s %s score %s below threshold %s", news_id, symbol, score, min_score)
                self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
                return False

            allowed = [s.upper().strip() for s in ALLOWED_LIVE_SOURCES]
            # v5.3: Hardened source restriction (independent of policy mode string)
            if source_name not in allowed:
                logger.info("Source restricted: %s from %s (ingest-only)", symbol, source_name)
                self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
                return False
            
            # v5.2.3: Removal of khusus source suppression logic
            # if source_name == "NSE_BULK":
            #     val = float(item.get("deal_value_cr", 0))
            #     if val < 5.0:
            #         logger.info("Bulk suppression: %s value ₹%s Cr < ₹5 Cr", symbol, val)
            #         self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
            #         return False

            # v5.4.1: Unified Policy Enforcement (Standardized for Score 8+)
            if "ECONOMIC" in source_name or "MONEYCONTROL" in source_name:
                if score < 8 and "ULTRA_STRICT" in ALERT_POLICY_MODE:
                    logger.info("Media suppression: %s is ingest-only (Score %s < 8)", symbol, score)
                    self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
                    return False
                else:
                    logger.info("Media alert candidate: %s with Score %s", symbol, score)


            if market_on and self.daily_alerts_count >= DAILY_ALERT_HARD_CAP:
                if score < 9:
                    logger.warning(
                        "Budget exhausted (%s/%s). Suppression: %s",
                        self.daily_alerts_count,
                        DAILY_ALERT_HARD_CAP,
                        symbol,
                    )
                    self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
                    return False
                logger.info("[CAP_BYPASS_9_10] Emergency signal for %s (%s/10)", symbol, score)

            now_ts = time.time()
            last_ts = self.db.get_symbol_last_alert_ts(symbol)
            if last_ts is not None:
                gap = (now_ts - last_ts) / 60
                if gap < SYMBOL_COOLDOWN_MIN:
                    if score >= 9:
                        logger.info("[BYPASS_COOLDOWN] Priority alert for %s (%s/10)", symbol, score)
                    else:
                        logger.info("Cooldown hit: %s (%s min)", symbol, int(gap))
                        self.db.mark_analysis_complete(news_id, score, sentiment, alerted=False)
                        return False

            # Re-check timing right before final routing for boundary accuracy.
            market_on = self.is_market_hours()

            # v5.1: Final Dispatch Logic
            if not market_on:
                logger.info("Market session inactive: Queuing %s for morning dispatch (status=3)", symbol)
                self.db.mark_analysis_complete(
                    news_id, score, sentiment,
                    trigger=analysis.get("trigger"),
                    perspective=analysis.get("sector"),
                    alerted=False,
                    status=3
                )
                return False

            # MARKET ON: LIVE SIGNAL
            # v5.6: Background dispatch with automatic disk cleanup
            dispatch_coro = self.bot.send_signal(item, analysis, pdf_path=pdf_path)
            task = asyncio.create_task(dispatch_coro)
            
            # Ensure PDF is deleted ONLY after the task finishes
            def _cleanup_pdf(_t):
                if pdf_path and os.path.exists(pdf_path):
                    try: os.remove(pdf_path)
                    except: pass
            task.add_done_callback(_cleanup_pdf)
            
            self.db.mark_alert_sent(news_id)
            self.daily_alerts_count += 1
            self.db.set_symbol_cooldown(symbol, now_ts)
            logger.info("Intelligence Hand-off: #%s %s queued for dispatch (%s/10)", self.daily_alerts_count, symbol, score)

            if market_on:
                asyncio.create_task(self.impact_tracker.start_tracking(news_id, symbol, score, sentiment))

            self.db.mark_analysis_complete(
                news_id, score, sentiment,
                trigger=analysis.get("trigger"),
                perspective=analysis.get("sector"),
                alerted=True,
            )
            return analysis
        except Exception as e:
            logger.error("Critical failure in _process_single_item for %s: %s", item.get('symbol', 'N/A'), e)
            self.db.set_processing_status(news_id, 0)
            return None
        finally:
            # v5.6: Handled by background task or manual cycle cleanup in main loop
            pass

        # return analysis (v5.2.3: Removed redundant return)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Institutional Intelligence Engine")
    parser.add_argument("--health", action="store_true", help="Run system health checks and exit.")
    args = parser.parse_args()

    check_single_instance()
    system = MarketIntelligenceSystem()

    if args.health:
        success = await system.health_check()
        sys.exit(0 if success else 1)

    await system.start_background_tasks()

    from nse_monitor.config import ENABLE_EMBEDDED_ADMIN_BOT
    if ENABLE_EMBEDDED_ADMIN_BOT:
        from admin_bot import AdminPanel

        admin_panel = AdminPanel()
        asyncio.create_task(admin_panel.run())
        logger.info("Admin dashboard bot started (embedded mode).")
    else:
        logger.info("Embedded admin bot disabled. Use standalone admin_bot.py process.")

    if not await system.health_check():
        logger.critical("FATAL: Health check failed. Shutting down.")
        sys.exit(1)

    scheduler = MarketScheduler(system)
    asyncio.create_task(scheduler.start())

    logger.info("Starting startup warmup (3 forced cycles).")
    for i in range(3):
        try:
            logger.info("Warmup cycle %s/3", i + 1)
            await system.run_cycle()
            await asyncio.sleep(5)
        except Exception as exc:
            logger.error("Warmup cycle %s failed: %s", i + 1, exc)

    logger.info("Warmup complete. System entering high-trust monitoring mode.")

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Shutdown signal received in event loop. Closing sessions...")
    finally:
        # Graceful cleanup to prevent 'Unclosed client session' errors
        try: 
            await system.bot.close()
        except: pass
        try: 
            if hasattr(system, 'llm_processor') and hasattr(system.llm_processor, 'close'):
                await system.llm_processor.close()
        except: pass
        try:
            if system.nse_client and hasattr(system.nse_client, 'session') and system.nse_client.session:
                await system.nse_client.session.close()
        except: pass
        try:
            if system.health_session:
                await system.health_session.close()
        except: pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Graceful shutdown received.")
    except Exception as exc:
        logger.critical("FATAL: %s", exc, exc_info=True)
