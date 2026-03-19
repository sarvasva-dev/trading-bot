import sqlite3
import os
import sys
from dotenv import load_dotenv

# Add nse_monitor to path to get DB_PATH
load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nse_monitor.config import DB_PATH

def migrate():
    print(f"Starting migration for database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # TEST PHASE: Wipe DB if requested
        if os.getenv("TEST_MODE_WIPE_DB", "0") == "1":
            print("TEST_MODE: Wiping ALL tables for a fresh start...")
            cursor.execute("DROP TABLE IF EXISTS alerts")
            cursor.execute("DROP TABLE IF EXISTS event_clusters")
            cursor.execute("DROP TABLE IF EXISTS news_items")
            cursor.execute("DROP TABLE IF EXISTS processed_announcements")
            conn.commit()

        # Ensure news_items table exists (Standardized with database.py)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                headline TEXT,
                summary TEXT,
                url TEXT UNIQUE,
                timestamp TEXT,
                embedding BLOB,
                cluster_id INTEGER,
                perspective TEXT, 
                impact_score INTEGER, 
                sentiment TEXT,
                intraday_probability INTEGER DEFAULT 0,
                trade_quality TEXT,
                content_hash TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("PRAGMA table_info(news_items)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'news_items' in [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            print("Migrating news_items table...")
            
            # Add missing columns
            missing_cols = {
                'cluster_id': 'INTEGER',
                'perspective': 'TEXT',
                'impact_score': 'INTEGER',
                'sentiment': 'TEXT'
            }
            
            for col, col_type in missing_cols.items():
                if col not in columns:
                    print(f"Adding column {col} to news_items...")
                    cursor.execute(f"ALTER TABLE news_items ADD COLUMN {col} {col_type}")

            # Remove 'category' column if it exists (SQLite doesn't easily support DROP COLUMN in old versions, so we'll just leave it or rename if needed. 
            # In modern SQLite 3.35.0+ we can DROP. Let's try DROP and catch if fails.)
            if 'category' in columns:
                try:
                    cursor.execute("ALTER TABLE news_items DROP COLUMN category")
                    print("Dropped legacy 'category' column.")
                except Exception as e:
                    print(f"Could not drop 'category' (likely old SQLite version): {e}")

        # 2. Ensure event_clusters table exists
        print("Ensuring event_clusters table exists...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_clusters (
                cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Ensure alerts table exists
        print("Ensuring alerts table exists...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id INTEGER,
                sent_to_telegram INTEGER DEFAULT 0,
                FOREIGN KEY (news_id) REFERENCES news_items (id)
            )
        """)

        # 4. Create v7.0 Performance Indexes (Only if table exists)
        if 'news_items' in [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            print("Creating indexes...")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_timestamp ON news_items(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_id ON news_items(cluster_id)")
        else:
            print("Table 'news_items' not found. Skipping migration (Bot will auto-initialize).")

        conn.commit()
        print("Migration COMPLETED successfully.")

    except Exception as e:
        print(f"Migration FAILED: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
