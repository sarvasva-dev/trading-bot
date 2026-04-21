import sqlite3
import os
from datetime import datetime

# Path to the database on the VPS (copied from config.py logic)
DB_PATH = "/home/ipynb/trading-bot/nse_monitor/data/processed_announcements.db"

def run_diagnostic():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("--- DB DIAGNOSTIC (TODAY'S ACTIVITY) ---")
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Check for Pending News
    cursor.execute("SELECT COUNT(*) FROM news_items WHERE processing_status = 0")
    pending = cursor.fetchone()[0]
    print(f"Total Pending Items: {pending}")

    # 2. Check for Analyzed but Blocked News Today
    print("\n--- Last 10 Analyzed Items Today ---")
    cursor.execute("""
        SELECT symbol, impact_score, sentiment, processing_status, headline 
        FROM news_items 
        WHERE date(created_at) = date('now', 'localtime')
        ORDER BY created_at DESC 
        LIMIT 15
    """)
    rows = cursor.fetchall()
    if not rows:
        print("No items analyzed today yet.")
    for row in rows:
        sym, score, sent, status, head = row
        alert_str = "SUCCESS" if status == 2 else "BLOCKED"
        print(f"[{alert_str}] {sym} | Score: {score} | Sent: {sent} | {head[:60]}...")

    # 3. Check for Successful Alerts Today
    cursor.execute("SELECT COUNT(*) FROM alert_dispatch_log WHERE date(dispatch_time) = date('now', 'localtime')")
    alerts = cursor.fetchone()[0]
    print(f"\nTotal Dispatched Today: {alerts}")

    conn.close()

if __name__ == "__main__":
    run_diagnostic()
