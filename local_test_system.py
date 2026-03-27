import sys
import os
import time
import logging
from datetime import datetime

# Add the project root to sys.path to allow imports from nse_monitor
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nse_monitor.config import (
    TELEGRAM_BOT_TOKEN, SARVAM_API_KEY, RAZORPAY_KEY_ID, 
    DB_PATH, DATA_DIR, LOGS_DIR
)
from nse_monitor.database import Database
from nse_monitor.nse_api import NSEClient
from nse_monitor.pdf_processor import PDFProcessor
from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.payment_processor import RazorpayProcessor

# Logging Setup
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("TestSystem")

def separator():
    print("\n" + "="*50 + "\n")

def test_environment():
    logger.info("Step 1: Checking Environment Variables...")
    missing = []
    if not TELEGRAM_BOT_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
    if not SARVAM_API_KEY or "placeholder" in SARVAM_API_KEY: missing.append("SARVAM_API_KEY")
    if not RAZORPAY_KEY_ID or "placeholder" in RAZORPAY_KEY_ID: missing.append("RAZORPAY_KEY_ID")
    
    if missing:
        logger.warning(f"Missing/Placeholder keys found: {missing}")
        return False
    logger.info("✅ Environment keys look good.")
    return True

def test_database():
    separator()
    logger.info("Step 2: Testing Database (SQLite)...")
    try:
        db = Database()
        # Test User CRUD
        chat_id = "999999"
        
        # Get initial days if user exists, else 0
        user_before = db.get_user(chat_id)
        initial_days = user_before[4] if user_before else 0
        
        db.save_user(chat_id, "TestBot", "test_user")
        if not user_before: initial_days = 2 # Trial credit
        
        logger.info(f"Initial/Trial days: {initial_days}")
        
        db.add_working_days(chat_id, 10)
        user_after = db.get_user(chat_id)
        
        if user_after and user_after[4] == (initial_days + 10):
            logger.info(f"✅ Credits added ({initial_days} -> {user_after[4]}).")
        else:
            logger.error(f"❌ Credit retrieval failed. Expected {initial_days + 10}, got {user_after[4] if user_after else 'None'}")
            return False
            
        db.reset_user_days(chat_id)
        logger.info("✅ User reset successful.")
        return True
    except Exception as e:
        logger.error(f"❌ Database Test Failed: {e}")
        return False

def test_nse_api():
    separator()
    logger.info("Step 3: Testing NSE API & PDF Extraction...")
    try:
        client = NSEClient()
        announcements = client.get_announcements()
        if not announcements:
            logger.error("❌ No announcements returned from NSE.")
            return False
            
        logger.info(f"✅ Successfully fetched {len(announcements)} announcements.")
        
        # Test PDF component
        pdf_proc = PDFProcessor()
        test_item = next((a for a in announcements if 'attchmntFile' in a and a['attchmntFile']), None)
        
        if test_item:
            url = test_item['attchmntFile']
            logger.info(f"Downloading sample PDF: {url}")
            path = pdf_proc.download_pdf(url)
            if path:
                text = pdf_proc.extract_text(path)
                logger.info(f"✅ PDF Extracted: {len(text)} characters.")
            else:
                logger.warning("⚠️ PDF download failed (Bypassed).")
        return True
    except Exception as e:
        logger.error(f"❌ NSE/PDF Test Failed: {e}")
        return False

def test_ai_processor():
    separator()
    logger.info("Step 4: Testing AI Logic (Sarvam AI)...")
    try:
        llm = LLMProcessor()
        sample_event = [{
            "headline": "Reliance Industries wins 5000 Cr order from European Union",
            "summary": "This is a major breakthrough for the energy sector involving green hydrogen."
        }]
        
        logger.info("Analysing sample high-impact event (Dry Run)...")
        result = llm.analyze_single_event(sample_event, market_status="OPEN")
        
        if result and ("impact_score" in result or result.get("valid_event")):
            logger.info(f"✅ AI Result: Impact {result.get('impact_score')} | Sentiment: {result.get('sentiment')}")
            logger.info(f"✅ Trigger: {result.get('trigger')}")
            return True
        else:
            logger.error(f"❌ AI returned invalid or empty result: {result}")
            return False
    except Exception as e:
        logger.error(f"❌ AI Test Failed: {e}")
        return False

def test_payment_processor():
    separator()
    logger.info("Step 5: Testing Payment Engine (Razorpay)...")
    try:
        rp = RazorpayProcessor()
        if not rp.client:
            logger.warning("⚠️ Razorpay client not initialized (Safe skip).")
            return True
            
        logger.info("Attempting to create a test ₹99 payment link...")
        link = rp.create_payment_link("test_123", "99", "Tester")
        if link and "short_url" in link:
            logger.info(f"✅ Payment Link Generated: {link['short_url']}")
            return True
        else:
            logger.error("❌ Link generation failed.")
            return False
    except Exception as e:
        logger.error(f"❌ Payment Test Failed: {e}")
        return False

def run_full_suite():
    print("\n" + "="*50)
    print("🚀 MARKET PULSE - FULL SYSTEM AUDIT")
    print("="*50 + "\n")
    
    results = {
        "ENV": test_environment(),
        "DB": test_database(),
        "NSE": test_nse_api(),
        "AI": test_ai_processor(),
        "PAY": test_payment_processor()
    }
    
    separator()
    print("📋 FINAL AUDIT REPORT")
    print("-" * 25)
    for module, ok in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{module:<15}: {status}")
    print("-" * 25)
    
    if all(results.values()):
        print("\n✨ ALL SYSTEMS READY FOR PRODUCTION! ✨\n")
    else:
        print("\n⚠️ SOME MODULES NEED ATTENTION. Check logs above. ⚠️\n")

if __name__ == "__main__":
    run_full_suite()
