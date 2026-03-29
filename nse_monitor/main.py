import logging
import sys
import os
import hashlib
import time
import warnings
from datetime import datetime
import pytz
import threading
import atexit
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress warnings
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def check_single_instance():
    """Ensures only one instance of the bot is running using a PID file lock."""
    pid_file = "nsebot.pid"
    import psutil
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                logger.error(f"FATAL: Instance already running (PID {old_pid}).")
                sys.exit(1)
            else:
                os.remove(pid_file)
        except Exception:
            if os.path.exists(pid_file):
                os.remove(pid_file)
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.remove(pid_file) if os.path.exists(pid_file) else None)


from nse_monitor.config import (
    LOGS_DIR, ALERT_THRESHOLD, MAX_ALERTS_PER_HOUR, BOT_NAME,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, ROOT_DIR
)
from nse_monitor.database import Database
from nse_monitor.report_builder import ReportBuilder
from nse_monitor.telegram_bot import TelegramBot
from nse_monitor.sources.nse_source import NSESource
from nse_monitor.sources.nse_sme_source import NseSmeSource
from nse_monitor.sources.economic_times_source import EconomicTimesSource
from nse_monitor.sources.moneycontrol_source import MoneycontrolSource
from nse_monitor.sources.bulk_deal_source import BulkDealSource
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.watchdog import BotWatchdog
from nse_monitor.telegram_notifier import TelegramNotifier
from nse_monitor.trading_calendar import TradingCalendar

import logging.handlers

# ── Logging Setup ─────────────────────────────────────────────────────────────
def ist_time(*args):
    return datetime.now(pytz.timezone('Asia/Kolkata')).timetuple()

logging.Formatter.converter = ist_time
os.makedirs(LOGS_DIR, exist_ok=True)

# v1.3.3: Rotating Logs (Max 5MB per file, 3 backups)
_log_path = os.path.join(LOGS_DIR, "app.log")
_log_handler = logging.handlers.RotatingFileHandler(
    _log_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        _log_handler
    ]
)
logger = logging.getLogger("NSEPulse")


class MarketIntelligenceSystem:
    def __init__(self):
        logger.info(f"═══════════════════════════════════════════")
        logger.info(f"  {BOT_NAME} v1.0 — Industrial Engine Boot")
        logger.info(f"═══════════════════════════════════════════")

        self.ist = pytz.timezone("Asia/Kolkata")
        self.db = Database()

        # v1.3: Real-time 'IP Pressure' bridge for Admin Notifications
        def notify_admin_on_ban(alert_text):
            if hasattr(self, 'bot'):
                self.bot.send_admin_alert(alert_text)

        from nse_monitor.nse_api import NSEClient
        self.nse_client = NSEClient(on_403=notify_admin_on_ban)

        self.bot = TelegramBot(db=self.db, nse_client=self.nse_client)
        self.pdf_processor = PDFProcessor()
        self.llm_processor = LLMProcessor()
        self.report_builder = ReportBuilder(self.bot, self.db, self.llm_processor)
        self.calendar = TradingCalendar()

        # v1.0: Full source suite including SME
        self.sources = [
            NSESource(client=self.nse_client),
            NseSmeSource(client=self.nse_client),    # NEW: SME Segment
            EconomicTimesSource(),
            MoneycontrolSource(),
            BulkDealSource(nse_client=self.nse_client),
        ]

        # v1.0: Thematic Clustering Memory (symbol → last_alert_timestamp)
        self.alert_memory = {}

        # v1.1: Notifiers & Watchdog
        self.notifier = TelegramNotifier()
        log_file = os.path.join(ROOT_DIR, "logs", "service.log")
        self.watchdog = BotWatchdog(self.notifier, log_file)

        # v1.1: Thread-safe memory lock
        self.memory_lock = threading.Lock()

        # Threaded Telegram Handler
        self.bot.register_menu_commands()
        self.update_thread = threading.Thread(
            target=self._update_polling_loop, daemon=True
        )
        self.update_thread.start()

        logger.info("✅ All systems initialized. v1.0 Online.")

    def _update_polling_loop(self):
        """Background thread: handles Telegram user messages without blocking main cycle."""
        while True:
            try:
                self.bot.handle_updates()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Telegram Thread Error: {e}")
                time.sleep(5)

    def is_market_hours(self):
        """v1.0: Uses TradingCalendar for accurate market hours check."""
        now = datetime.now(self.ist)
        if not TradingCalendar.is_trading_day(now):
            return False
        return 9 <= now.hour < 16

    def eod_billing(self):
        """Runs at 16:00 IST to deduct 1 market day post-market."""
        now = datetime.now(self.ist)
        from nse_monitor.trading_calendar import TradingCalendar
        if TradingCalendar.is_trading_day(now):
            logger.info(f"📅 Post-Market Ledger EOD ({now.strftime('%d %b %Y')}): Decrementing user credits...")
            self.db.decrement_working_days()
        else:
            holiday_name = TradingCalendar.get_holiday_name(now)
            reason = f"NSE Holiday ({holiday_name})" if holiday_name else "Weekend"
            logger.info(f"🗓️ {reason}: Skipping Post-Market credit deduction.")

    def daily_maintenance(self):
        """
        v1.0: Runs at midnight IST.
        - Sends expiry reminders to exhausted users.
        - Runs DB maintenance and backup.
        """
        now = datetime.now(self.ist)

        # Send expiry reminders
        expired_users = self.db.get_expired_users()
        if expired_users:
            logger.info(f"Sending expiry reminders to {len(expired_users)} users...")
            for chat_id in expired_users:
                try:
                    self.bot._send_expiry_reminder(chat_id)
                except Exception:
                    continue

        # v1.3.3: DB Maintenance and Backup
        self.db.run_maintenance()
        self.db.backup()

    def send_preexpiry_reminders(self):
        """Runs at 6 PM IST — warns users with 1 day left."""
        users = self.db.get_expiring_soon_users()
        if not users:
            return
        logger.info(f"Sending 24h pre-expiry reminders to {len(users)} users...")
        for chat_id, first_name in users:
            try:
                msg = (
                    f"⚠️ <b>Heads up, {first_name}!</b>\n"
                    f"────────────────────────\n"
                    f"Your Market Pulse subscription expires <b>tomorrow</b>.\n\n"
                    f"Renew now to keep receiving institutional NSE signals. 📈\n"
                )
                self.bot._send_raw(chat_id, msg, {
                    "inline_keyboard": [
                        [{"text": "🔄 Renew Now", "callback_data": "sub_menu"}],
                        [{"text": "🛠️ Contact Admin", "url": "https://wa.me/917985040858"}]
                    ]
                })
            except Exception:
                continue

    def check_pending_payments(self):
        """Polls Razorpay for pending payment links and auto-activates on success."""
        pending_links = self.db.get_pending_payment_links()
        if not pending_links:
            return

        for pl_id, chat_id, days in pending_links:
            try:
                from nse_monitor.payment_processor import RazorpayProcessor
                rp = RazorpayProcessor()
                days_to_add = rp.verify_payment_status(pl_id)
                if days_to_add:
                    self.db.add_working_days(chat_id, days_to_add)
                    self.db.update_payment_link_status(pl_id, 'processed')
                    msg = (
                        f"✅ <b>Payment Successful!</b>\n"
                        f"────────────────────────\n"
                        f"Ref: <code>{pl_id}</code>\n\n"
                        f"<b>{days_to_add} Market Days</b> added. Use /plan to view expiry. 📈"
                    )
                    self.bot._send_raw(chat_id, msg)
                    logger.warning(f"AUTO-PAYMENT SUCCESS: {chat_id} | +{days_to_add} days")
            except Exception as e:
                logger.error(f"Error during auto-payment check for {pl_id}: {e}")

    # ── v1.0: ZERO-LOSS INTELLIGENCE CYCLE ───────────────────────────────────
    def run_cycle(self):
        """
        v1.0: Zero-Loss Intelligence Cycle.
        STEP 1: Fetch & Ingest — all new items go into DB as 'Pending' (status=0).
        STEP 2: Process — take 4 oldest Pending items, run them through AI.
        STEP 3: Dispatch — if score passes threshold, send via Async broadcaster.
        """
        logger.info("╔══════════════════════════════════════╗")
        logger.info("║   v1.0 Intelligence Cycle — START    ║")
        logger.info("╚══════════════════════════════════════╝")
        self.watchdog.heartbeat()

        # ── STEP 1: FETCH & INGEST ALL SOURCES ───────────────────────────────
        raw_items = []
        for source in self.sources:
            try:
                # v1.3.6: Skip NSE sources if not connected (Prevents cycle crashes)
                source_name = getattr(source, 'NAME', 'Unknown')
                if source_name in ("NSE", "NSE_SME") and not self.nse_client.is_connected:
                    logger.warning(f"⚠️ Source [{source_name}] skipped: NSE Client not connected yet.")
                    continue
                    
                items = source.fetch()
                if items:
                    tz = pytz.timezone("Asia/Kolkata")
                    now = datetime.now(tz)
                    # Noise filter
                    ignore_kw = [
                        "trading window", "shareholding pattern",
                        "compliance certificate", "postal ballot",
                        "record date for agm", "registered office"
                    ]
                    for item in items:
                        # v2.0: Media Mute Filter (Live Admin Control)
                        is_official = item.get("source") in ("NSE", "NSE_SME")
                        media_mute = self.db.get_config("media_mute", "0") == "1"
                        
                        if not is_official and media_mute:
                            logger.debug(f"🔇 Skipping Media item due to LIVE MUTE: {item.get('headline', '')[:50]}")
                            continue

                        if any(kw in item.get('headline', '').lower() for kw in ignore_kw):
                            continue

                        # Timestamp-based age filter (max 24h lookback)
                        ts_str = item.get('timestamp', '')
                        if ts_str:
                            try:
                                if 'T' in ts_str:
                                    ts = datetime.fromisoformat(
                                        ts_str.replace('Z', '+00:00')
                                    ).astimezone(tz)
                                elif '-' in ts_str and ':' in ts_str:
                                    if len(ts_str.split('-')[0]) == 4:
                                        ts = datetime.fromisoformat(ts_str).astimezone(tz)
                                    else:
                                        ts = datetime.strptime(
                                            ts_str, "%d-%b-%Y %H:%M:%S"
                                        ).replace(tzinfo=tz)
                                else:
                                    ts = now
                                age_min = (now - ts).total_seconds() / 60
                                if age_min > 1440:  # Older than 24h
                                    continue
                                item['age_minutes'] = age_min
                            except Exception:
                                item['age_minutes'] = 0

                        raw_items.append(item)
                    logger.info(f"Source [{source.NAME}]: {len(items)} fetched, after filter: {len(raw_items)} total so far.")
            except Exception as e:
                logger.error(f"Source [{getattr(source, 'NAME', '?')}] Fetch Error: {e}")

        # ── INGEST INTO DB (deduplication happens here) ───────────────────────
        ingested = 0
        for item in raw_items:
            # STEP 1.2: Identity Hash (v2.0 Unified)
            # Combines headline, symbol, and raw source id to prevent cross-source collisions
            raw_id = item.get('raw_id', '')
            hash_input = f"{item.get('headline', '').lower()}|{item.get('symbol', 'N/A').upper()}|{raw_id}"
            content_hash = hashlib.sha256(hash_input.encode()).hexdigest()
            
            existing_id, existing_source = self.db.news_exists(item.get("url"), content_hash)
            if existing_id:
                # v2.0 Upranking Logic: If existing is Media and new is Official, promote it.
                is_current_official = item.get("source") in ("NSE", "NSE_SME")
                is_existing_media = existing_source not in ("NSE", "NSE_SME")
                
                if is_current_official and is_existing_media:
                    logger.info(f"🔄 Upranking {existing_id}: {existing_source} -> {item.get('source')} (Official Filing found)")
                    self.db.update_news_source(existing_id, item.get("source"))
                continue

            item["content_hash"] = content_hash
            db_id = self.db.add_news_item(item)
            if db_id:
                ingested += 1

        logger.info(f"📥 Ingested {ingested} new items into Zero-Loss Queue.")

        # ── STEP 2: PROCESS TOP 4 PENDING ITEMS ─────────────────────────────
        pending_items = self.db.get_pending_news(limit=4)
        if not pending_items:
            logger.info("📡 Queue empty — no pending items to process this cycle.")
            return False

        logger.info(f"🔄 Processing {len(pending_items)} pending items from queue...")

        market_on = self.is_market_hours()
        alert_sent = False
        used_symbols = set()

        # v1.1 - Concurrent AI Processing using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(self._process_single_item, item, market_on) for item in pending_items]
            for future in as_completed(futures):
                try:
                    res = future.result()
                    if res: alert_sent = True
                except Exception as e:
                    logger.error(f"Error in concurrent AI task: {e}")

        return alert_sent

    def _process_single_item(self, item, market_on):
        """Worker method for processing a single news item concurrently."""
        news_id = item['db_id']
        alert_sent_flag = False

        # ── PDF Enrichment ───────────────────────────────────────────────
        if item.get("url"):
            try:
                pdf_path = self.pdf_processor.download_pdf(item["url"])
                text = self.pdf_processor.extract_text(pdf_path)
                if text and len(text) > 100:
                    meaningful = text[500:4000].strip()
                    item["summary"] = (item.get("summary", "") + f"\n[FILING EXTRACT]: {meaningful}")
                    self.db.update_news_summary(news_id, item["summary"])
            except Exception as e:
                logger.debug(f"PDF enrichment failed for {news_id}: {e}")

        # ── AI Analysis ──────────────────────────────────────────────────
        source_name = item.get("source", "NSE")
        analysis = self.llm_processor.analyze_single_event(
            [item],
            market_status="OPEN" if market_on else "CLOSED",
            source_name=source_name
        )

        if not analysis:
            logger.error(f"❌ AI returned None for: {item.get('headline', '')[:60]}")
            self.db.mark_analysis_complete(news_id, 0, "Neutral", alerted=False)
            return False

        score = analysis.get("impact_score", 0)
        valid = analysis.get("valid_event", False)

        is_official = source_name in ("NSE", "NSE_SME")
        from nse_monitor.config import ALERT_THRESHOLD
        
        # v2.0: Use Live Config from DB
        db_threshold = int(self.db.get_config("ai_threshold", ALERT_THRESHOLD))
        required_score = db_threshold if is_official else (db_threshold + 2)

        self.db.mark_analysis_complete(
            news_id, score, analysis.get("sentiment", "Neutral"),
            trigger=analysis.get("trigger"),
            perspective=analysis.get("sector"), alerted=False
        )

        if not valid or score < required_score:
            logger.info(f"Rejected: {item.get('headline', '')[:50]}... | Score: {score} | Required: {required_score}")
            return False

        # ── Thematic Deduplication (Thread Safe) ─────────────────────────
        symbol = str(analysis.get("symbol", "UNKNOWN")).upper()
        now_ts = time.time()
        
        with self.memory_lock:
            # Clean old entries (> 1 hour)
            self.alert_memory = {k: v for k, v in self.alert_memory.items() if now_ts - v < 3600}
            
            if symbol in self.alert_memory:
                last_time = self.alert_memory[symbol]
                mins_ago = int((now_ts - last_time) / 60)
                logger.info(f"🔇 Dedup: Suppressing duplicate alert for {symbol} (sent {mins_ago}m ago)")
                return False
                
            # Always record to memory (including UNKNOWN to prevent local cycle spam)
            self.alert_memory[symbol] = now_ts

        # ── SIGNAL DISPATCH (Synchronous inside ThreadPool Worker) ───────
        is_big = analysis.get("is_big_ticket", False)
        is_sme = analysis.get("is_sme", item.get("is_sme", False))
        is_time_critical = analysis.get("time_critical", False)
        
        # ── OFF-MARKET SUPPRESSION ───────────────────────────────────────
        should_send = market_on or score >= 9
        
        if should_send:
            self.bot.send_signal(item, analysis)
            self.db.mark_alert_sent(news_id)
            logger.info(f"🔥 ALERT DISPATCHED: {symbol} | Score: {score}/10 | {analysis.get('sentiment')} | {'🏦 SME' if is_sme else ''} {'🔥 BIG' if is_big else ''}")
        else:
            logger.info(f"🌙 OFF-MARKET: Suppressing broadcast for {symbol} (Score: {score}/10). Saved for morning report.")

        self.db.mark_analysis_complete(
            news_id, score, analysis.get("sentiment", "Neutral"),
            trigger=analysis.get("trigger"),
            perspective=analysis.get("sector"), alerted=should_send
        )
        return should_send

    def safe_run_cycle(self):
        """v1.3.3: Crash-protected wrapper with Automated Daily Backup."""
        try:
            # v1.3.3: Auto-Backup check before each cycle
            if self.db.needs_backup():
                self.db.backup()
                
            self.run_cycle()
        except Exception as e:
            logger.error(f"Cycle failure: {e}", exc_info=True)


def main():
    # v1.3.3: Graceful Shutdown Handlers
    def shutdown_signal_handler(sig, frame):
        logger.info(f"🚨 Received shutdown signal ({sig}). Finalizing system...")
        system.db.conn.close()
        logger.info("✅ Database flushed and closed. Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_signal_handler)
    signal.signal(signal.SIGTERM, shutdown_signal_handler)

    try:
        check_single_instance()
        
        # v1.3.7: Start Admin Dashboard FIRST (Ensures immediate responsiveness)
        try:
            from admin_bot import AdminPanel
            admin_p = AdminPanel()
            admin_thread = threading.Thread(target=admin_p.run, daemon=True)
            admin_thread.start()
            logger.info("✅ Admin Dashboard Bot started (Priority).")
        except Exception as e:
            logger.error(f"Failed to start Admin Bot: {e}")

        # Now start the Heavy Intelligence Engine
        system = MarketIntelligenceSystem()

        # Start Watchdog
        system.watchdog.start()

        # Start Scheduler
        from nse_monitor.scheduler import MarketScheduler
        scheduler = MarketScheduler(system)

        # Run first cycle immediately on startup
        logger.info("🚀 Running initial intelligence cycle on startup...")
        system.safe_run_cycle()

        # Hand off to scheduler (blocking)
        scheduler.start()

    except Exception as e:
        logger.critical(f"🔥 FATAL Boot Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
