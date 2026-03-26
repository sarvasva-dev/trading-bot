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

# Logging Setup
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(os.path.join(LOGS_DIR, "app.log"))]
)
logger = logging.getLogger("NSEPulse")

class MarketIntelligenceSystem:
    def __init__(self):
        logger.info("Initializing Signal Engine v7.5...")
        self.db = Database()
        self.bot = TelegramBot(db=self.db)
        self.pdf_processor = PDFProcessor()
        self.llm_processor = LLMProcessor()
        self.report_builder = ReportBuilder(self.bot, self.db, self.llm_processor)

        # RULE #1: NSE ONLY (Primary Institutional Intel)
        self.sources = [NSESource()]
        
        # RULE #18: Threaded Telegram Handler
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

    def run_cycle(self):
        """High-precision analysis cycle."""
        logger.info("Starting intelligence cycle...")
        
        # 1. Fetching
        raw_items = []
        for source in self.sources:
            try:
                items = source.get_announcements()
                if items:
                    # RULE #3 & #6: Strict Filtering
                    tz = pytz.timezone("Asia/Kolkata")
                    now = datetime.now(tz)
                    ignore = ["trading window", "shareholding pattern", "compliance certificate"]
                    
                    for item in items:
                        if any(kw in item['headline'].lower() for kw in ignore): continue
                        
                        try:
                            ts = item.get('datetime') or datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00')).astimezone(tz)
                            age = (now - ts).total_seconds() / 60
                            if age > 720: continue # 12h max
                            item['age_minutes'] = age
                        except: continue
                        
                        raw_items.append(item)
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

        if not new_items: return False

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
            
            if not analysis or not analysis.get("valid_event"): continue
            
            impact = analysis.get("impact_score", 0)
            if impact < 7: continue # RULE #12
            
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

