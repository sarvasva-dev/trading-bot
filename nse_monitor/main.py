import logging
import sys
import os
import hashlib
import time
import difflib
import schedule
import warnings
from datetime import datetime
import pytz

import atexit
import signal

import threading

# Suppress warnings
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def check_single_instance():
    """Ensures only one instance of the bot is running using a PID file lock."""
    pid_file = "nsebot.pid"
    if os.path.isfile(pid_file):
        try:
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())
            try:
                os.kill(old_pid, 0)
                logger.error(f"FATAL: Instance already running (PID {old_pid}).")
                sys.exit(1)
            except OSError:
                if os.path.exists(pid_file): os.remove(pid_file)
        except:
             if os.path.exists(pid_file): os.remove(pid_file)
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.remove(pid_file) if os.path.exists(pid_file) else None)

from nse_monitor.config import LOGS_DIR, ALERT_THRESHOLD, MAX_ALERTS_PER_HOUR, BOT_NAME
from nse_monitor.database import Database
from nse_monitor.report_builder import ReportBuilder
from nse_monitor.telegram_bot import TelegramBot
from nse_monitor.sources.nse_source import NSESource
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.sources.economic_times_source import EconomicTimesSource
from nse_monitor.sources.moneycontrol_source import MoneycontrolSource
from nse_monitor.sources.bulk_deal_source import BulkDealSource

# Logging Setup
def ist_time(*args):
    return datetime.now(pytz.timezone('Asia/Kolkata')).timetuple()

logging.Formatter.converter = ist_time

os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(os.path.join(LOGS_DIR, "app.log"))]
)
logger = logging.getLogger("NSEPulse")

class MarketIntelligenceSystem:
    def __init__(self):
        logger.info("Initializing Signal Engine v11.0 (Admin Mastery)...")
        self.db = Database()
        from nse_monitor.nse_api import NSEClient
        self.nse_client = NSEClient()
        self.bot = TelegramBot(db=self.db, nse_client=self.nse_client)
        self.pdf_processor = PDFProcessor()
        self.llm_processor = LLMProcessor()
        self.report_builder = ReportBuilder(self.bot, self.db, self.llm_processor)

        # RULE #1: NSE ONLY (Primary Institutional Intel) | RULE #14: Multi-Source Support
        self.sources = [
            NSESource(client=self.nse_client),
            EconomicTimesSource(),
            MoneycontrolSource(),
            BulkDealSource()
        ]
        
        # RULE #18: Threaded Telegram Handler
        self.bot.register_menu_commands()
        self.update_thread = threading.Thread(target=self._update_polling_loop, daemon=True)
        self.update_thread.start()

    def _update_polling_loop(self):
        while True:
            try:
                self.bot.handle_updates()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Telegram Thread Error: {e}")
                time.sleep(5)

    def is_market_hours(self):
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        return 9 <= now.hour < 16 and now.weekday() < 5

    def daily_maintenance(self):
        """Runs at midnight IST to decrement market days and send reminders."""
        now = datetime.now(self.ist)
        # 1. Decrement credits (ONLY Mon-Fri)
        if now.weekday() <= 4:
            logger.info("Market Day Detected. Decrementing user credits...")
            self.db.decrement_working_days()
        else:
            logger.info("Weekend Detected. Skipping subscription decrement.")

        # 2. Send Expiry Reminders to EXPIRED users (Every day)
        expired_users = self.db.get_expired_users()
        if expired_users:
            logger.info(f"Sending expiry reminders to {len(expired_users)} users...")
            for chat_id in expired_users:
                try:
                    self.bot._send_expiry_reminder(chat_id)
                except: continue

    def send_preexpiry_reminders(self):
        """Runs at 6 PM IST — warns users with exactly 1 day left to renew."""
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
                    f"Renew now to keep receiving institutional NSE signals without any interruption. 📈\n"
                )
                self.bot._send_raw(chat_id, msg, {
                    "inline_keyboard": [
                        [{"text": "🔄 Renew Now", "callback_data": "sub_menu"}],
                        [{"text": "🛠️ Contact Admin", "url": "https://wa.me/917985040858"}]
                    ]
                })
            except: continue

    def check_pending_payments(self):
        """Polls Razorpay for the status of pending links (Rule #24)."""
        pending_links = self.db.get_pending_payment_links()
        if not pending_links: return
        
        for pl_id, chat_id, days in pending_links:
            try:
                days_to_add = self.payment_processor.verify_payment_status(pl_id)
                if days_to_add:
                    # 1. Credit the user
                    self.db.add_working_days(chat_id, days_to_add)
                    # 2. Mark as processed
                    self.db.update_payment_link_status(pl_id, 'processed')
                    # 3. Notify user (Rule #24)
                    msg = (
                        f"✅ <b>Payment Successful!</b>\n"
                        f"────────────────────────\n"
                        f"We've verified your transaction (Ref: <code>{pl_id}</code>).\n\n"
                        f"<b>{days_to_add} Market Days</b> have been added to your account.\n"
                        f"Use /plan to see your new expiry date. 📈"
                    )
                    self.bot._send_raw(chat_id, msg)
                    logger.warning(f"AUTO-PAYMENT SUCCESS: {chat_id} | +{days_to_add} days")
                else:
                    # Plan days might be 0 but status could be paid? 
                    # verify_payment_status returns 'days' only if paid.
                    pass
            except Exception as e:
                logger.error(f"Error during auto-payment check for {pl_id}: {e}")

    def start(self):
        """Initializes all polling and reporting jobs."""
        logger.info(f"Initializing {BOT_NAME} Schedule (v12.0)...")
        
        # 1. Market Intel Polling (Every 3 Minutes)
        self.scheduler.add_job(self.safe_run_cycle, 'interval', minutes=3, id='market_cycle')
        
        # 2. Daily Morning Report (08:30 AM IST)
        self.scheduler.add_job(self.report_builder.generate_morning_report, 'cron', 
                               hour=8, minute=30, id='morning_report', timezone=self.ist)
        
        # 3. User Message Polling (Every 1 Minute)
        self.scheduler.add_job(self.bot.handle_updates, 'interval', minutes=1, id='bot_updates')

        # 4. Midnight Maintenance (00:00 IST) - Rule #24
        self.scheduler.add_job(self.daily_maintenance, 'cron', hour=0, minute=0, id='midnight_sync', timezone=self.ist)
        
        # 5. Auto-Payment Verification (Every 1 Minute) - Rule #24
        self.scheduler.add_job(self.check_pending_payments, 'interval', minutes=1, id='payment_poller')

        # 6. 24h Pre-Expiry Reminder (6:00 PM IST) - v12.0
        self.scheduler.add_job(self.send_preexpiry_reminders, 'cron',
                               hour=18, minute=0, id='preexpiry_reminder', timezone=self.ist)

        logger.info("Scheduler started (08:30 IST Reports | 18:00 Pre-Expiry | 1-Min Auto-Pay | 3-Min Polling).")
        self.scheduler.start()

    def safe_run_cycle(self):
        """Wrapper for run_cycle to catch exceptions."""
        try:
            self.run_cycle()
        except Exception as e:
            logger.error(f"Error during scheduled run_cycle: {e}", exc_info=True)

    def run_cycle(self):
        """High-precision analysis cycle."""
        logger.info("Starting intelligence cycle...")
        
        # 1. Fetching
        raw_items = []
        for source in self.sources:
            try:
                # Fixed: Use .fetch() instead of .get_announcements()
                items = source.fetch()
                if items:
                    # RULE #3 & #6: Strict Filtering
                    tz = pytz.timezone("Asia/Kolkata")
                    now = datetime.now(tz)
                    ignore = ["trading window", "shareholding pattern", "compliance certificate"]
                    
                    logger.info(f"Filtering {len(items)} items for {BOT_NAME} purity...")
                    passed_age = 0
                    for item in items:
                        if any(kw in item['headline'].lower() for kw in ignore): continue
                        
                        try:
                            # Enhanced Institutional Parser (Rule #2)
                            ts_str = item.get('timestamp', '')
                            if not ts_str: continue
                            
                            try:
                                # Try standard formats used by NSE
                                if '-' in ts_str and ':' in ts_str:
                                    if len(ts_str.split('-')[0]) == 4: # YYYY-MM-DD
                                        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).astimezone(tz)
                                    else: # DD-MM-YYYY or DD-Mon-YYYY
                                        ts = datetime.strptime(ts_str, "%d-%b-%Y %H:%M:%S").astimezone(tz)
                                else:
                                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')).astimezone(tz)
                            except:
                                # Fallback for simple date
                                ts = datetime.strptime(ts_str.split('.')[0], "%Y-%m-%dT%H:%M:%S").astimezone(tz) if 'T' in ts_str else now

                            age = (now - ts).total_seconds() / 60
                            # Increased to 24 hours for better test visibility
                            if age > 1440: continue 
                            item['age_minutes'] = age
                            passed_age += 1
                        except Exception as e:
                            logger.debug(f"Timestamp Parse Skip: {e} | Data: {ts_str}")
                            continue
                        
                        raw_items.append(item)
                    logger.info(f"Purity Filter: {passed_age} items passed age/noise criteria.")
            except Exception as e:
                logger.error(f"Source Fetch Error: {e}")

        # 2. Ingestion
        new_items = []
        for item in raw_items:
            # Check by URL and Content Hash
            content_hash = hashlib.sha256(item['headline'].encode()).hexdigest()
            if self.db.news_exists(item.get("url"), content_hash): continue
            
            item["content_hash"] = content_hash
            item["db_id"] = self.db.add_news_item(item)
            new_items.append(item)

        if not new_items:
            logger.info(f"📡 Scanning... {len(raw_items)} NSE items evaluated. No new institutional triggers in this cycle.")
            return False

        # 3. Processing
        processed_count = 0
        used_sectors = set()
        alert_sent = False
        market_on = self.is_market_hours()

        for item in new_items:
            if processed_count >= 4: break # RULE #14
            
            # PDF Data Extraction
            if item.get("url"):
                pdf_path = self.pdf_processor.download_pdf(item["url"])
                text = self.pdf_processor.extract_text(pdf_path)
                if text:
                    item["summary"] += f"\n[FILING]: {text[:3000]}"
                    self.db.update_news_summary(item["db_id"], item["summary"])

            # AI Institutional Logic (22 Rules)
            analysis = self.llm_processor.analyze_single_event([item], market_status="OPEN" if market_on else "CLOSED")
            
            if not analysis:
                logger.error(f"❌ [AI FAILURE] {item.get('symbol', 'N/A')}: LLM returned None or parse error.")
                continue
                
            if not analysis.get("valid_event"): 
                logger.info(f"⏩ [AI SKIP] {item.get('symbol', 'N/A')}: Filtered by AI (Invalid/Concluded).")
                continue
            
            import nse_monitor.config as config
            impact = analysis.get("impact_score", 0)
            sentiment = analysis.get("sentiment", "Neutral")
            
            if impact < config.ALERT_THRESHOLD:
                logger.info(f"📉 [AI RESULT] {item.get('symbol', 'N/A')} | Score: {impact} | Status: Rejected (Below Threshold)")
                continue
            
            logger.info(f"🔥 [AI ALERT] {item.get('symbol', 'N/A')} | Score: {impact} | sentiment: {sentiment} -> BROADCASTING")
            
            sector = analysis.get("sector", "Unknown")
            if sector in used_sectors and impact < 8: continue # RULE #15 diversity

            # Speed Check (RULE #4)
            if market_on and item.get('age_minutes', 99) >= 5 and impact < 8: continue

            # Final Alert
            if self.bot.send_alert({
                "symbol": analysis.get("symbol", "N/A"),
                "trigger": analysis.get("trigger", "N/A"),
                "url": item["url"],
                "impact_score": impact,
                "sentiment": analysis.get("sentiment", "Neutral"),
                "ai_report": analysis
            }):
                self.db.mark_alert_sent(item["db_id"])
                alert_sent = True
                processed_count += 1
                used_sectors.add(sector)
            
            time.sleep(5)

        return alert_sent

def main():
    try:
        check_single_instance()
        system = MarketIntelligenceSystem()
        
        # 🟢 Start Admin Dashboard Bot (v8.0)
        try:
            from admin_bot import AdminPanel
            admin_p = AdminPanel()
            import threading
            admin_thread = threading.Thread(target=admin_p.run, daemon=True)
            admin_thread.start()
            logger.info("Admin Dashboard Bot started (Parallel Thread).")
        except Exception as e:
            logger.error(f"Failed to start Admin Bot: {e}")

        from nse_monitor.scheduler import MarketScheduler
        scheduler = MarketScheduler(system)
        system.run_cycle()
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("User stopped.")
    except Exception as e:
        logger.critical(f"FATAL: {e}", exc_info=True)

if __name__ == "__main__":
    main()

