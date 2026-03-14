import sqlite3
import logging
from nse_monitor.config import DB_PATH, DATA_DIR
import os

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_announcements (
                    id TEXT PRIMARY KEY,
                    company TEXT,
                    timestamp TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def is_processed(self, announcement_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM processed_announcements WHERE id = ?", (announcement_id,))
        return cursor.fetchone() is not None

    def mark_processed(self, announcement_id, company, timestamp):
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO processed_announcements (id, company, timestamp) VALUES (?, ?, ?)",
                    (announcement_id, company, timestamp)
                )
        except sqlite3.IntegrityError:
            pass # Already processed

if __name__ == "__main__":
    db = Database()
    db.mark_processed("test_123", "Test Co", "2024-01-01")
    print(f"Is processed: {db.is_processed('test_123')}")
