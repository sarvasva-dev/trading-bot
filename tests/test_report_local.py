import sys
import os
import logging
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.report_builder import ReportBuilder
from nse_monitor.database import Database
from nse_monitor.llm_processor import LLMProcessor

# Mock Telegram Bot for Testing
class MockBot:
    def send_report(self, text):
        print("\n\n=== 🚀 GENERATED REPORT START ===")
        print(text)
        print("=== 🚀 GENERATED REPORT END ===\n")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Initializing components...")
    db = Database()
    llm = LLMProcessor()
    bot = MockBot()
    
    report_builder = ReportBuilder(bot, db, llm)
    
    # Force print current time check
    tz = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(tz)
    print(f"Current Admin Time (IST): {now_ist}")
    print(f"Is Monday? {'Yes' if now_ist.weekday() == 0 else 'No'}")
    
    print("Running Report Generation Test...")
    # Passing hours=48 to ensure we capture some data for the test
    # (Since this is a test, we don't rely only on the automatic logic)
    print(report_builder.build_pre_market_report(hours=48))
