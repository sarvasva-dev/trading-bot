import sqlite3
import os

DB_PATH = '/home/ipynb/trading-bot/data/market_intelligence.db'

def reset_today():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check how many items from today
    cursor.execute("SELECT count(*) FROM news_items WHERE created_at > date('now', 'localtime')")
    count = cursor.fetchone()[0]
    
    # Delete them
    cursor.execute("DELETE FROM news_items WHERE created_at > date('now', 'localtime')")
    
    # Delete from processed_announcements (if exists)
    try:
        cursor.execute("DELETE FROM processed_announcements WHERE timestamp > date('now', 'localtime')")
    except sqlite3.OperationalError:
        pass # Table might not exist
        
    conn.commit()
    conn.close()
    
    print(f"✅ Successfully deleted {count} news items from today!")
    print("Next cycle will re-fetch and re-analyze ALL of today's news.")

if __name__ == "__main__":
    reset_today()
