import time
import logging
import sys
from datetime import datetime
from nse_monitor.nse_api import NSEClient
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.database import Database
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.telegram_bot import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("nse_monitor.log")
    ]
)
logger = logging.getLogger("NSEMonitor")

def main():
    logger.info("Initializing NSE Monitor System...")
    
    try:
        nse = NSEClient()
        pdf = PDFProcessor()
        db = Database()
        llm = LLMProcessor()
        bot = TelegramBot()
    except Exception as e:
        logger.error(f"Critical error during initialization: {e}")
        sys.exit(1)

    logger.info("Monitor started. Checking every 60 seconds.")
    
    while True:
        try:
            logger.info("Starting a new check cycle...")
            announcements = nse.get_announcements()
            
            if not announcements:
                logger.info("No announcements found or request failed.")
            else:
                for ann in sorted(announcements, key=lambda x: x.get('dt', '')):
                    # Use a stable unique ID
                    # Some announcements might have sm_pid, others id
                    raw_id = str(ann.get('sm_pid') or ann.get('id') or f"{ann.get('symbol')}-{ann.get('dt')}-{ann.get('desc', '')[:20]}")
                    
                    if not db.is_processed(raw_id):
                        company = ann.get('symbol') or ann.get('sm_name', 'Unknown')
                        desc = ann.get('desc') or ann.get('subject', 'No description')
                        pdf_url = ann.get('attchmntFile') or ann.get('attachmentUrl')

                        logger.info(f"New announcement detected for {company}: {desc[:50]}...")
                        
                        pdf_path = None
                        extracted_text = ""
                        if pdf_url:
                            pdf_path = pdf.download_pdf(pdf_url)
                            extracted_text = pdf.extract_text(pdf_path)

                        # Process with LLM
                        context = f"Headline: {desc}\n\nPDF Content:\n{extracted_text[:4000]}"
                        ai_report = llm.analyze_news(company, context)
                        
                        # Prepare Telegram Data
                        alert_data = {
                            "symbol": company,
                            "desc": desc,
                            "pdf_url": pdf_url,
                            "ai_report": ai_report
                        }
                        
                        # Send Notification
                        bot.send_alert(alert_data)
                        
                        # Mark as processed
                        # Extracting a timestamp for the DB
                        ann_dt = ann.get('dt') or ann.get('annDate') or datetime.now().strftime("%Y-%m-%d")
                        db.mark_processed(raw_id, company, ann_dt)
                        
                        # Anti-spam delay between processing
                        time.sleep(2)
                    
            logger.info("Cycle complete. Waiting 60 seconds...")
            time.sleep(60)
            
        except KeyboardInterrupt:
            logger.info("Stopping monitor...")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
