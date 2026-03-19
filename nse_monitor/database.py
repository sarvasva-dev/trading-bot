import sqlite3
import os
import logging
from nse_monitor.config import DB_PATH

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        with self.conn:
            # High Performance Pragmas
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            
            # Legacy table for NSE Announcements
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_announcements (
                    id TEXT PRIMARY KEY,
                    company TEXT,
                    timestamp TEXT,
                    content_hash TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Unified table for all news sources (Updated for v7.0)
            self.conn.execute("""
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

            # Event Clusters table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS event_clusters (
                    cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Alert Tracking table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER,
                    sent_to_telegram INTEGER DEFAULT 0,
                    FOREIGN KEY (news_id) REFERENCES news_items (id)
                )
            """)
            
            # v7.0 Performance Indexes
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_news_timestamp ON news_items(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cluster_id ON news_items(cluster_id)")

    def get_alert_count_last_hour(self):
        """Returns the number of alerts sent in the last 60 minutes."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(id) FROM alerts WHERE sent_to_telegram = 1 AND news_id IN (SELECT id FROM news_items WHERE created_at > datetime('now', '-1 hour'))"
        )
        return cursor.fetchone()[0]

    def is_processed(self, announcement_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM processed_announcements WHERE id = ?", (announcement_id,))
        return cursor.fetchone() is not None

    def mark_processed(self, announcement_id, company, timestamp, content_hash):
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO processed_announcements (id, company, timestamp, content_hash) VALUES (?, ?, ?, ?)",
                    (announcement_id, company, timestamp, content_hash)
                )
        except sqlite3.IntegrityError:
            pass

    def is_url_duplicate(self, url):
        """Checks if a URL has already been processed in the last 24 hours."""
        if not url:
            return False
        cursor = self.conn.cursor()
        
        # Check in processed_announcements table (URL column)
        cursor.execute("SELECT id FROM news_items WHERE url = ?", (url,))
        return cursor.fetchone() is not None

    def is_content_duplicate(self, headline, content_hash):
        """Checks if content is duplicate based on Hash OR Headline."""
        cursor = self.conn.cursor()
        
        # 1. Content Hash Check (Global Exact Match)
        if content_hash:
            cursor.execute("SELECT id FROM news_items WHERE content_hash = ?", (content_hash,))
            if cursor.fetchone(): return True
        
        # 2. Headline Check (Headline Match within 48 hours to allow recurring reports)
        if headline:
            cursor.execute(
                "SELECT id FROM news_items WHERE headline = ? AND created_at > datetime('now', '-2 days')", 
                (headline,)
            )
            if cursor.fetchone(): return True

        return False

    def news_exists(self, url, content_hash):
        """Checks if a news item already exists based on URL or Content Hash."""
        cursor = self.conn.cursor()
        
        # Check by URL first (most reliable for exact duplicates)
        if url:
            cursor.execute("SELECT id FROM news_items WHERE url = ?", (url,))
            if cursor.fetchone():
                return True
                
        # Fallback to content hash check
        if content_hash:
            cursor.execute("SELECT id FROM news_items WHERE content_hash = ?", (content_hash,))
            if cursor.fetchone():
                return True
                
        return False

    # Updated Methods for Event-Driven Intelligence (v7.0)
    def add_news_item(self, item):
        """Initial ingestion of news item. Returns the new row ID.
           Accepts a dictionary 'item' as input.
        """
        try:
            with self.conn:
                cursor = self.conn.execute(
                    """INSERT OR IGNORE INTO news_items 
                       (source, headline, summary, url, timestamp, content_hash) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (item.get("source"), item.get("headline"), item.get("summary"), 
                     item.get("url"), item.get("timestamp"), item.get("content_hash"))
                )
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def update_news_analysis(self, news_id, embedding, cluster_id, perspective, impact_score, sentiment, probability=0, quality=None):
        """Updates news item with AI/ML analysis results."""
        try:
            with self.conn:
                self.conn.execute("""
                    UPDATE news_items 
                    SET embedding = ?, cluster_id = ?, perspective = ?, impact_score = ?, sentiment = ?,
                        intraday_probability = ?, trade_quality = ?
                    WHERE id = ?
                """, (embedding, cluster_id, perspective, impact_score, sentiment, probability, quality, news_id))
        except Exception as e:
            logger.error(f"Error updating news analysis: {e}")

    def update_news_summary(self, news_id, summary):
        """Updates the summary/text for an existing news item (e.g., after PDF extraction)."""
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE news_items SET summary = ? WHERE id = ?",
                    (summary, news_id)
                )
        except Exception as e:
            logger.error(f"Error updating news summary: {e}")

    def get_recent_news_for_clustering(self, hours=48):
        """Fetches recent news embeddings to find similar events."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, embedding, cluster_id, headline FROM news_items WHERE created_at > datetime('now', ?)",
            (f"-{hours} hours",)
        )
        return cursor.fetchall()

    def create_cluster(self, topic):
        """Creates a new event cluster and returns ID."""
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO event_clusters (topic) VALUES (?)",
                (topic,)
            )
            return cursor.lastrowid

    def update_cluster_time(self, cluster_id):
        """Updates the last_updated timestamp of a cluster."""
        with self.conn:
            self.conn.execute(
                "UPDATE event_clusters SET last_updated = CURRENT_TIMESTAMP WHERE cluster_id = ?",
                (cluster_id,)
            )

    def get_cluster_topic(self, cluster_id):
        """Fetches the topic for a specific cluster ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT topic FROM event_clusters WHERE cluster_id = ?", (cluster_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_latest_news(self, min_impact=0, perspective=None, sentiment=None, hours=24):
        """Fetches news filtered by impact score, perspective, and sentiment."""
        cursor = self.conn.cursor()
        query = """SELECT n.headline, n.summary, n.source, n.url, n.impact_score 
                   FROM news_items n
                   WHERE n.impact_score >= ? AND n.created_at > datetime('now', ?)"""
        params = [min_impact, f"-{hours} hours"]
        
        if perspective:
            query += " AND n.perspective = ?"
            params.append(perspective)
        if sentiment:
            query += " AND n.sentiment = ?"
            params.append(sentiment)
            
        query += " ORDER BY n.impact_score DESC"
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def mark_alert_sent(self, news_id):
        """Registers that an alert was sent for this news item."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO alerts (news_id, sent_to_telegram) VALUES (?, 1)",
                (news_id,)
            )

    def get_recent_news(self, hours=24):
        """Fetches recent news items for AI deduplication."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, headline, summary FROM news_items WHERE created_at > datetime('now', ?)",
            (f"-{hours} hours",)
        )
        return [{"id": row[0], "headline": row[1], "summary": row[2]} for row in cursor.fetchall()]
