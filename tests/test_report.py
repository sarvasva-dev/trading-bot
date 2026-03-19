import sys
import os
import logging
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nse_monitor.database import Database
from nse_monitor.report_builder import ReportBuilder

logging.basicConfig(level=logging.INFO)

db = Database()
print("Stats: Latest News Count")
latest = db.get_latest_news(min_impact=0, hours=240)
print(f"Found {len(latest)} items in the last 240 hours.")

builder = ReportBuilder(db)
report = builder.build_pre_market_report(hours=240)
print("\n--- GENERATED REPORT ---")
print(report)
print("------------------------")
