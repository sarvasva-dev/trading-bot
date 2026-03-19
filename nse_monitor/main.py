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

# Suppress warnings from HuggingFace/Transformers
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from nse_monitor.config import LOGS_DIR
from nse_monitor.database import Database
from nse_monitor.clusterer import EventClusterer
from nse_monitor.classifier import NewsClassifier
from nse_monitor.report_builder import ReportBuilder
from nse_monitor.telegram_bot import TelegramBot
from nse_monitor.sources.nse_source import NSESource
from nse_monitor.sources.moneycontrol_source import MoneycontrolSource
from nse_monitor.sources.economic_times_source import EconomicTimesSource
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.email_notifier import EmailNotifier
try:
    from nse_monitor.config import MAX_AI_PER_CYCLE, AI_COOLDOWN_SECONDS
except ImportError:
    MAX_AI_PER_CYCLE = 20
    AI_COOLDOWN_SECONDS = 1

# Force UTF-8 for console output on Windows
try:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, Exception):
    pass

# Set up logging early
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOGS_DIR, "app.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("MarketIntelBot")

class MarketIntelligenceSystem:
    def __init__(self):
        logger.info(" Market Intelligence Bot: Starting Services...")
        self.db = Database()
        self.bot = TelegramBot()
        self.pdf_processor = PDFProcessor()
        self.llm_processor = LLMProcessor()
        self.email_notifier = EmailNotifier()
        self.classifier = NewsClassifier()
        self.clusterer = EventClusterer()
        self.report_builder = ReportBuilder(self.bot, self.db)

        # Initialize Sources
        # Optimized Order as per User Request: News sources first, then Official Filing
        self.sources = [
            MoneycontrolSource(),
            EconomicTimesSource(),
            NSESource()
        ]
        
    def is_market_hours(self):
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        current_time = now.time()
        # Market open 9:00 - 15:30
        start = datetime.strptime("09:00", "%H:%M").time()
        end = datetime.strptime("15:30", "%H:%M").time()
        return start <= current_time <= end and now.weekday() < 5

    def run_cycle(self):
        """Main execution cycle running every 5 minutes."""
        logger.info("\n Starting Intelligence Cycle...")
        cycle_start = time.time()
        
        # 1. Fetch from all sources
        raw_items = []
        for source in self.sources:
            try:
                logger.info(f" Fetching from {source.NAME}...")
                
                # Handling different method names across sources for compatibility
                if hasattr(source, 'fetch_news'):
                    items = source.fetch_news()
                elif hasattr(source, 'fetch'):
                    items = source.fetch()
                elif hasattr(source, 'get_announcements'):
                    items = source.get_announcements()
                else:
                    logger.error(f"Source {source.NAME} has no valid fetch method")
                    continue
                    
                if items:
                    raw_items.extend(items)
                time.sleep(3) # Polite delay
            except Exception as e:
                logger.error(f"Source Error ({source.NAME}): {e}")

        # 2. Filter & Register New Items
        new_items = []
        for item in raw_items:
            # Generate ID based on Content
            content_hash = hashlib.sha256(
                f"{item['headline']}{item['summary']}".encode()
            ).hexdigest()

            # Skip duplicates (Robust Check)
            if self.db.is_url_duplicate(item.get("url")) or \
               self.db.is_content_duplicate(item.get("headline"), content_hash):
                continue

            # Add to Database Immediately
            item["content_hash"] = content_hash
            db_id = self.db.add_news_item(item)
            item["db_id"] = db_id
            new_items.append(item)

        if not new_items:
            logger.info(" No new unique items found.")
            return False

        logger.info(f" Found {len(new_items)} new unique items. Preparing for Analysis...")

        # 3. SMART GROUPING LOGIC (Single Event Method)
        # Groups multiple sources for the same event into one "Event Packet"
        
        events_to_process = []
        unprocessed_pool = new_items[:] # Copy of list
        matcher = difflib.SequenceMatcher(None, "", "")

        while unprocessed_pool:
            # Take the first item as the "Base" of a new event group
            base_item = unprocessed_pool.pop(0)
            current_event_group = [base_item]
            
            # Search pool for related items (duplicates or cross-source matches)
            indices_to_remove = []
            
            for i, candidate in enumerate(unprocessed_pool):
                # Check A: Exact specific URL match (rare but possible)
                if candidate.get("url") and candidate["url"] == base_item.get("url"):
                    current_event_group.append(candidate)
                    indices_to_remove.append(i)
                    continue

                # Check B: Headline Similarity (Fuzzy Match > 60%)
                matcher.set_seq2(base_item["headline"].lower())
                matcher.set_seq1(candidate["headline"].lower())
                similarity = matcher.ratio()
                
                if similarity > 0.60:
                    current_event_group.append(candidate)
                    indices_to_remove.append(i)
            
            # Remove grouped items from pool (reverse order to keep indices valid)
            for i in sorted(indices_to_remove, reverse=True):
                del unprocessed_pool[i]
            
            events_to_process.append(current_event_group)

        # 4. Process Each Event Group
        logger.info(f" Grouped {len(new_items)} items into {len(events_to_process)} unique events.")
        
        alert_sent_this_cycle = False
        market_on = self.is_market_hours()
        recent_news = self.db.get_recent_news(hours=24) # Fetch once for context

        for event_group in events_to_process:
            # === DEDUPLICATION CHECK (DB BASED) ===
            # Avoid sending the same event twice even if headlines differ slightly
            current_headline = event_group[0]["headline"]
            current_ids = [item["db_id"] for item in event_group]
            is_semantic_duplicate = False
            
            if recent_news:
                for old_item in recent_news:
                    # SELF-CHECK PREVENTION: Do not compare against itself!
                    if old_item["id"] in current_ids:
                        continue

                    # Fuzzy Match Ratio
                    # Check both headline and summary for stronger match context
                    similarity_head = difflib.SequenceMatcher(None, current_headline.lower(), old_item["headline"].lower()).ratio()
                    
                    if similarity_head > 0.60:
                        logger.info(f" ♻️ Skipped Semantic Duplicate: '{current_headline}' matches existing '{old_item['headline']}' ({int(similarity_head*100)}%)")
                        is_semantic_duplicate = True
                        break
            
            if is_semantic_duplicate:
                continue
            
            # Pre-processing: PDF Extraction for NSE items in the group
            for item in event_group:
                if item["source"] == "NSE" and item.get("url"):
                    logger.info(f" Extracting PDF for: {item['headline'][:40]}...")
                    pdf_path = self.pdf_processor.download_pdf(item["url"])
                    raw_text = self.pdf_processor.extract_text(pdf_path)
                    if raw_text:
                        item["summary"] += f"\n[INTERNAL FILING TEXT]: {raw_text[:5000]}"
                        self.db.update_news_summary(item["db_id"], item["summary"])
            
            # Call AI for Single Event Analysis
            logger.info(f" Analyzing Event: {event_group[0]['headline'][:60]} ({len(event_group)} sources)")
            
            # === THE NEW SINGLE EVENT CALL ===
            market_status_str = "OPEN" if market_on else "CLOSED"
            # Removed recent_news passing to save tokens since we do DB pre-check now
            analysis = self.llm_processor.analyze_single_event(event_group, market_status=market_status_str)
            
            if not analysis or not analysis.get("valid_event", False):
                logger.info(" AI Rejected Event (Low relevance/Old/Opinion)")
                continue

            # Update Database for ALL items in this group with the SAME analysis result
            impact_score = analysis.get("impact_score", 0)
            prob = analysis.get("probability", 0)
            quality = analysis.get("trade_quality", "AVOID")
            
            lead_item = event_group[0] # Default lead
            
            # Find best lead item (prefer NSE if available)
            for item in event_group:
                if item["source"] == "NSE":
                    lead_item = item
                    break

            for item in event_group:
                self.db.update_news_analysis(
                    news_id=item["db_id"],
                    embedding=None,
                    cluster_id=None, # Pending proper clustering integration if needed
                    perspective=analysis.get("expected_move", "Neutral"),
                    impact_score=impact_score,
                    sentiment=analysis.get("sentiment", "Neutral"),
                    probability=prob,
                    quality=quality
                )

            # ALERT LOGIC
            logger.info(f" AI Result: Impact {impact_score}/10 | Prob {prob}% | {quality}")
            
            # Allow alerts for POSSIBLE MOVE (50%+) and up, REJECT 'AVOID'
            # SPECIAL RULE: Moneycontrol/ET often have "Market News" with lower specific impact but high relevance
            is_news_source = any(s in ["Moneycontrol", "Economic Times"] for s in [i["source"] for i in event_group])
            
            should_alert = False
            if (impact_score >= 6 or prob >= 50) and "AVOID" not in quality:
                should_alert = True
            elif is_news_source and (impact_score >= 4 or prob >= 40):
                # Lower threshold for News Sources to catch specialized reports
                should_alert = True

            # --- STRICT MARKET HOURS ENFORCEMENT ---
            if not market_on:
                should_alert = False
                logger.debug(" Market Closed. Alert suppressed (Saved for Morning Report).")

            if should_alert:
                sources_names = list(set([i["source"] for i in event_group]))
                alert_data = {
                    "symbol": analysis.get("symbol", "MARKET"),
                    "source": " & ".join(sources_names), # "NSE & MoneyControl"
                    "desc": analysis.get("headline"),
                    "url": lead_item["url"],
                    "impact_score": impact_score,
                    "probability": prob,
                    "trade_quality": quality,
                    "sentiment": analysis.get("sentiment", "Neutral"),
                    "ai_report": {
                        "headline": analysis.get("headline"),
                        "summary": analysis.get("summary"),
                        "key_insight": analysis.get("key_insight"),
                        "impact": analysis.get("sentiment"), # Map sentiment to impact field for display
                        "quantum": "High", # Simplified
                        "duration": "Intraday",
                        "sentiment": analysis.get("sentiment"),
                        "expected_move": analysis.get("expected_move")
                    }
                }
                
                if self.bot.send_alert(alert_data):
                    self.db.mark_alert_sent(lead_item["db_id"])
                    alert_sent_this_cycle = True
            else:
                logger.info(f" Skipped Alert ({lead_item['source']}): Impact {impact_score} Prob {prob}% Quality {quality}")
            
            # Polite delay between AI calls
            time.sleep(20)

        logger.info(f" Cycle Complete. Analyzed {len(events_to_process)} events.")
        return alert_sent_this_cycle

def main():
    try:
        system = MarketIntelligenceSystem()
        
        # Initial Boot Check
        system.run_cycle()
        
        # Schedule Loop
        import schedule
        schedule.every(5).minutes.do(system.run_cycle)
        
        # Background: Morning Report (Now at 09:00 AM as per new strategy)
        schedule.every().day.at("09:00").do(system.report_builder.generate_morning_report)

        logger.info(" Entering Main Loop...")
        while True:
            # Check for new Telegram users/messages periodically
            # This ensures auto-registration of new users without restarting
            system.bot.handle_updates()
            
            schedule.run_pending()
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info(" Logic Stopped by User.")
    except Exception as e:
        logger.critical(f" Critical Failure: {e}", exc_info=True)
        # Optional: Email Alert on Crash
        # system.email_notifier.send_failure_alert(str(e))

if __name__ == "__main__":
    main()

