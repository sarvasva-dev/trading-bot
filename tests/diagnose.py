import os
import requests
import fitz
import logging
from nse_monitor.nse_api import NSEClient
from nse_monitor.pdf_processor import PDFProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Diagnostic")

def run_diagnostics():
    logger.info("Starting Diagnostics...")
    
    # 1. Test NSE API
    logger.info("--- Testing NSE API ---")
    client = NSEClient()
    announcements = client.get_announcements()
    if announcements:
        logger.info(f"SUCCESS: Found {len(announcements)} announcements.")
    else:
        logger.error("FAILED: Could not fetch announcements.")
        return

    # 2. Test PDF Download & Extraction
    logger.info("--- Testing PDF Download & Extraction ---")
    pdf_proc = PDFProcessor()
    
    # Find first item with a PDF
    test_item = next((a for a in announcements if a.get('attchmntFile')), None)
    
    if test_item:
        pdf_url = test_item.get('attchmntFile')
        logger.info(f"Target PDF: {pdf_url}")
        
        path = pdf_proc.download_pdf(pdf_url)
        if path and os.path.exists(path):
            size = os.path.getsize(path)
            logger.info(f"SUCCESS: PDF Downloaded to {path} ({size} bytes)")
            
            text = pdf_proc.extract_text(path)
            if text:
                logger.info(f"SUCCESS: Extracted {len(text)} characters.")
                logger.info(f"Sample Text: {text[:200]}...")
            else:
                logger.warning("WARNING: PDF extracted but NO TEXT found (Might be a scanned image/scan).")
        else:
            logger.error(f"FAILED: Could not download PDF from {pdf_url}")
    else:
        logger.warning("No PDFs found in current announcements to test.")

if __name__ == "__main__":
    run_diagnostics()
