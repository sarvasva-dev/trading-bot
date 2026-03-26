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

            # User Tracking table (Rule #24)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    is_active INTEGER DEFAULT 1,
                    premium_until TIMESTAMP,
                    working_days_left INTEGER DEFAULT 0,
                    is_trial_used INTEGER DEFAULT 0,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Migration check: Ensure new columns exist in legacy databases
            try:
                self.conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
            except: pass 
            try:
                self.conn.execute("ALTER TABLE users ADD COLUMN premium_until TIMESTAMP")
            except: pass
            try:
                self.conn.execute("ALTER TABLE users ADD COLUMN working_days_left INTEGER DEFAULT 0")
            except: pass
            try:
                self.conn.execute("ALTER TABLE users ADD COLUMN is_trial_used INTEGER DEFAULT 0")
            except: pass
            
            # Payment Links table (Rule #24 - Auto-Activation)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_links (
                    link_id TEXT PRIMARY KEY,
                    chat_id TEXT,
                    days INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    def save_user(self, chat_id, first_name, username):
        """Saves a user and credits a 2-day free trial for first-time registrations."""
        with self.conn:
            # Check if user already exists
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, is_trial_used FROM users WHERE id = ?", (str(chat_id),))
            user = cursor.fetchone()
            
            if not user:
                # New user: Give 2 free market days
                logger.info(f"🆕 NEW USER REGISTERED: {first_name} ({chat_id}) | Credited 2-day trial.")
                self.conn.execute("""
                    INSERT INTO users (id, first_name, username, working_days_left, is_trial_used, is_active)
                    VALUES (?, ?, ?, 2, 1, 1)
                """, (str(chat_id), first_name, username))
                return True # New registration
            return False

    def get_user_count(self):
        """Returns the total number of unique users."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]

    def add_working_days(self, chat_id, days):
        """Credits a user with Market Days and activates them (UPSERT)."""
        with self.conn:
            # First, ensure user exists (fallback registration)
            self.conn.execute("""
                INSERT OR IGNORE INTO users (id, first_name, username, is_active, working_days_left)
                VALUES (?, 'Manual', 'manual_entry', 1, 0)
            """, (str(chat_id),))
            
            # Then update days
            self.conn.execute("""
                UPDATE users 
                SET working_days_left = working_days_left + ?, 
                    is_active = 1 
                WHERE id = ?
            """, (days, str(chat_id)))

    def decrement_working_days(self):
        """Decrements 1 day from all active users (To be called on weekdays)."""
        with self.conn:
            # 1. Decrement days
            self.conn.execute("UPDATE users SET working_days_left = working_days_left - 1 WHERE working_days_left > 0")
            # 2. Deactivate users with 0 days left
            self.conn.execute("UPDATE users SET is_active = 0 WHERE working_days_left <= 0")

    def toggle_user_status(self, chat_id, active=1):
        """Activates or deactivates a user's subscription."""
        with self.conn:
            self.conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (active, str(chat_id)))

    def sync_user(self, chat_id, first_name, username):
        """Updates user's name/username to keep database fresh (Rule #24)."""
        with self.conn:
            self.conn.execute("""
                UPDATE users 
                SET first_name = ?, username = ? 
                WHERE id = ?
            """, (first_name, username, str(chat_id)))

    def reset_user_days(self, chat_id):
        """Sets a user's working days to 0 and deactivates them (Rule #24)."""
        with self.conn:
            self.conn.execute("UPDATE users SET working_days_left = 0, is_active = 0 WHERE id = ?", (str(chat_id),))

    def get_active_users(self):
        """Fetches all users with an active subscription."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users WHERE is_active = 1")
        return [row[0] for row in cursor.fetchall()]

    def get_expired_users(self):
        """Fetches all users with 0 working days left for daily reminders."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users WHERE working_days_left <= 0")
        return [row[0] for row in cursor.fetchall()]

    def get_expiring_soon_users(self):
        """Fetches users with exactly 1 day left — for 24h pre-expiry reminders."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, first_name FROM users WHERE working_days_left = 1 AND is_active = 1")
        return cursor.fetchall()

    def search_users(self, query):
        """Search users by name or ID for admin /find command."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, first_name, username, is_active, working_days_left FROM users WHERE id LIKE ? OR first_name LIKE ? OR username LIKE ? LIMIT 5",
            (f"%{query}%", f"%{query}%", f"%{query}%")
        )
        return cursor.fetchall()

    def get_user_stats(self):
        """Returns total and active user counts."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(is_active) FROM users")
        return cursor.fetchone()

    def get_all_users(self, limit=20):
        """Fetches latest registered users with status."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, first_name, username, is_active, working_days_left FROM users ORDER BY registered_at DESC LIMIT ?", (limit,))
        return cursor.fetchall()

    def get_user(self, chat_id):
        """Fetches a single user's detailed status (Rule #24)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, first_name, username, is_active, working_days_left FROM users WHERE id = ?", (str(chat_id),))
        return cursor.fetchone()

    def get_recent_news(self, hours=24):
        """Fetches recent news items for AI deduplication."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, headline, summary, impact_score, url, source, symbol FROM news_items WHERE created_at > datetime('now', ?)",
            (f"-{hours} hours",)
        )
        return [{"id": row[0], "headline": row[1], "summary": row[2], "impact_score": row[3], "url": row[4], "source": row[5], "symbol": row[6]} for row in cursor.fetchall()]

    def save_payment_link(self, link_id, chat_id, days):
        """Stores a new payment link for background polling (Rule #24)."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO payment_links (link_id, chat_id, days, status) VALUES (?, ?, ?, 'pending')",
                (link_id, str(chat_id), days)
            )

    def get_pending_payment_links(self):
        """Fetches all links that haven't been confirmed as paid yet."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT link_id, chat_id, days FROM payment_links WHERE status = 'pending'")
        return cursor.fetchall()

    def update_payment_link_status(self, link_id, status):
        """Updates the status of a payment link (e.g., 'paid', 'expired')."""
        with self.conn:
            self.conn.execute("UPDATE payment_links SET status = ? WHERE link_id = ?", (status, link_id))
