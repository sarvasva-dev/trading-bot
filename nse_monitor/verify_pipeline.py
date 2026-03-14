import logging
import os
import sys
from nse_monitor.nse_api import NSEClient
from nse_monitor.database import Database
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.pdf_processor import PDFProcessor

# Setup Logging to Console
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Verify")

def verify():
    logger.info("--- Starting NSE Monitor Verification (xAI Integration) ---")
    
    # 1. Check API Fetching
    client = NSEClient()
    logger.info("Fetching real data from NSE API...")
    data = client.get_announcements()
    if not data:
        logger.error("Failed to fetch data from NSE. Check connectivity.")
        return
    
    logger.info(f"Successfully fetched {len(data)} announcements.")
    item = data[0]
    logger.info(f"Sample Item: {item.get('sm_name')} - {item.get('desc')}")

    # 2. Check Database
    db = Database()
    file_url = item.get('attchmntFile', 'test.pdf')
    ann_id = f"VERIFY_XAI_{item.get('symbol')}_{os.path.basename(file_url)}"
    
    logger.info("Testing DB persistence...")
    if db.is_processed(ann_id):
        with db.conn:
            db.conn.execute("DELETE FROM processed_announcements WHERE id = ?", (ann_id,))
    
    db.mark_processed(ann_id, item.get('sm_name'), item.get('an_dt'))
    if db.is_processed(ann_id):
        logger.info("SUCCESS: Database recorded the announcement.")

    # 3. Real AI Analysis using xAI
    logger.info("Testing Real AI Analysis using xAI (Grok)...")
    llm = LLMProcessor()
    
    # Try analyzing the subject directly for a quick test
    analysis = llm.analyze_announcement(
        company=item.get('sm_name'),
        subject=item.get('desc'),
        text="Sample announcement text: Quarterly profit increased by 15% due to robust sales in the vertical."
    )
    
    if analysis and analysis.get("headline"):
        logger.info(f"xAI Output Success!")
        logger.info(f"Headline: {analysis.get('headline')}")
        logger.info(f"Impact: {analysis.get('impact')}")
        logger.info(f"Summary: {analysis.get('summary')}")
    else:
        logger.error(f"xAI Output Failed: {analysis}")

    logger.info("--- Verification Complete ---")

if __name__ == "__main__":
    verify()
