import sqlite3
import os
import logging
import threading
import pytz
import time
from datetime import datetime
from nse_monitor.config import DB_PATH, ADMIN_SESSION_TIMEOUT_MINUTES

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        try:
            self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self.lock = threading.Lock()
            # v1.3.2: Increased busy timeout for high-concurrency scalability
            self.conn.execute("PRAGMA busy_timeout = 30000")
            # Test connection immediately
            self.conn.execute("SELECT 1")
            self._create_table()
            self._migrate_schema()
        except sqlite3.DatabaseError as e:
            if "malformed" in str(e).lower():
                logger.error(f"âŒ DATABASE CORRUPTED: {e}. Initiating auto-rescue...")
                self._handle_malformed()
            else:
                raise e

    def _handle_malformed(self):
        """v2.0: Rescues the system from a 'malformed' error by backing up and resetting."""
        import shutil
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{DB_PATH}.malformed_{timestamp}.bak"
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
            shutil.move(DB_PATH, backup_path)
            logger.warning(f"âš ï¸ Corrupted DB moved to {backup_path}")
            # Re-init
            self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self.lock = threading.Lock()
            self._create_table()
            self._migrate_schema()
            logger.info("âœ… Database reset successfully. Re-ingest starting...")
        except Exception as ex:
            logger.critical(f"ðŸ”¥ FATAL: Database recovery failed: {ex}")

    def _create_table(self):
        with self.conn:
            # v1.3.2: Industrial Concurrency (WAL mode + FULL sync)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            
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

            # Unified table for all news sources (v1.0 â€” Zero-Loss Queue)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    symbol TEXT,
                    headline TEXT,
                    summary TEXT,
                    url TEXT UNIQUE,
                    timestamp TEXT,
                    embedding BLOB,
                    cluster_id INTEGER,
                    perspective TEXT,
                    impact_score INTEGER,
                    sentiment TEXT,
                    trigger TEXT,
                    intraday_probability INTEGER DEFAULT 0,
                    trade_quality TEXT,
                    content_hash TEXT UNIQUE,
                    processing_status INTEGER DEFAULT 0,
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
                    is_active INTEGER DEFAULT 0,
                    working_days_left INTEGER DEFAULT 0,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Billing Audit Trail (v2.0 â€” Transparency)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS user_billing_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT,
                    event_type TEXT, -- 'DEBIT' | 'CREDIT' | 'RESET'
                    amount INTEGER,
                    reason TEXT,     -- 'Trading Day Deduction' | 'Manual Grant' | 'Payment'
                    balance_after INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
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
            
            # System Config table (v2.0 â€” Live Admin Controls)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # v2.0: Admin Session Persistent Authentication
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    chat_id TEXT PRIMARY KEY,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # v4.0: Instrumented Alert Dispatch Log & Impact Tracking
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_dispatch_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER,
                    symbol TEXT,
                    dispatch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    score INTEGER,
                    sentiment TEXT,
                    trigger_class TEXT,
                    price_start REAL,
                    price_15m REAL,
                    price_60m REAL,
                    price_eod REAL,
                    accuracy_score REAL,
                    FOREIGN KEY (news_id) REFERENCES news_items (id)
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_time ON alert_dispatch_log(dispatch_time)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_symbol ON alert_dispatch_log(symbol)")

            # Initial Config Seeds
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('ai_threshold', '5')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('media_mute', '0')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('last_backup', '0')")
            

            # v1.3.2: Auto-Migration for Zero-Loss Queue (Self-Healing)
            # Checks if processing_status exists, if not, adds it to legacy databases.
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA table_info(news_items)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'processing_status' not in columns:
                logger.warning("ðŸ”„ Upgrading Database: Adding 'processing_status' column to news_items...")
                self.conn.execute("ALTER TABLE news_items ADD COLUMN processing_status INTEGER DEFAULT 0")

            # v4.0: instrumented auto-migration for alert_dispatch_log
            cursor.execute("PRAGMA table_info(alert_dispatch_log)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'trigger_class' not in columns:
                logger.warning("ðŸ”„ Upgrading Database: Adding 'trigger_class' to alert_dispatch_log...")
                self.conn.execute("ALTER TABLE alert_dispatch_log ADD COLUMN trigger_class TEXT")
            if 'accuracy_score' not in columns:
                logger.warning("ðŸ”„ Upgrading Database: Adding 'accuracy_score' to alert_dispatch_log...")
                self.conn.execute("ALTER TABLE alert_dispatch_log ADD COLUMN accuracy_score REAL")

            # v1.0 Performance Indexes
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_news_timestamp ON news_items(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cluster_id ON news_items(cluster_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_processing_status ON news_items(processing_status)")
            
            # v1.3.2: Scalability Indexes for high user counts
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_billing_cid ON user_billing_log(chat_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_reg ON users(registered_at)")

    def _migrate_schema(self):
        """v2.0: Centralized migration logic to ensure schema consistency across versions."""
        cursor = self.conn.cursor()
        
        # Table: news_items
        cursor.execute("PRAGMA table_info(news_items)")
        news_cols = [row[1] for row in cursor.fetchall()]
        
        for col, col_type in [("trigger", "TEXT"), ("symbol", "TEXT"), ("processing_status", "INTEGER DEFAULT 0")]:
            if col not in news_cols:
                try:
                    with self.conn:
                        self.conn.execute(f"ALTER TABLE news_items ADD COLUMN {col} {col_type}")
                        logger.info(f"Migration: Added {col} to news_items.")
                except Exception as e:
                    logger.error(f"Migration failed ({col}): {e}")

        # Table: users
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [row[1] for row in cursor.fetchall()]
        
        # v1.3.1: Professional Marketing Columns
        for col, col_type in [
            ("working_days_left", "INTEGER DEFAULT 0"),
            ("is_trial_used", "INTEGER DEFAULT 0"),
            ("source_tag", "TEXT DEFAULT 'direct'")
        ]:
            if col not in user_cols:
                try:
                    with self.conn:
                        self.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                        logger.info(f"Migration: Added {col} to users table.")
                except Exception as e:
                    logger.error(f"Migration failed (users.{col}): {e}")

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
        """v2.0: Returns (id, source) if news exists, else (None, None). Supports upranking."""
        cursor = self.conn.cursor()
        
        # Check by URL first (most reliable for exact duplicates)
        if url:
            cursor.execute("SELECT id, source FROM news_items WHERE url = ?", (url,))
            res = cursor.fetchone()
            if res: return res
                
        # Fallback to content hash check
        if content_hash:
            cursor.execute("SELECT id, source FROM news_items WHERE content_hash = ?", (content_hash,))
            res = cursor.fetchone()
            if res: return res
                
        return None, None

    def update_news_source(self, news_id, new_source):
        """v2.0: Upranks news source (e.g., from Media to NSE)."""
        with self.conn:
            self.conn.execute("UPDATE news_items SET source = ? WHERE id = ?", (new_source, news_id))

    # v1.0 Zero-Loss Queue Methods
    def add_news_item(self, item):
        """Initial ingestion of a news item into the queue (status=0: Pending)."""
        try:
            with self.lock:
                with self.conn:
                    cursor = self.conn.execute(
                        """INSERT OR IGNORE INTO news_items 
                           (source, symbol, headline, summary, url, timestamp, content_hash, processing_status) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                        (item.get("source"), item.get("symbol"), item.get("headline"),
                         item.get("summary"), item.get("url"), item.get("timestamp"),
                         item.get("content_hash"))
                    )
                    return cursor.lastrowid if cursor.lastrowid else None
        except sqlite3.IntegrityError:
            return None

    def get_pending_news(self, limit=4):
        """v1.0: Fetches oldest unprocessed news items from the queue.
           processing_status=0 means Pending. Limit=4 ensures we do 4 per cycle max.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT id, source, symbol, headline, summary, url, timestamp
               FROM news_items
               WHERE processing_status = 0
               ORDER BY created_at ASC
               LIMIT ?""",
            (limit,)
        )
        rows = cursor.fetchall()
        return [
            {"db_id": r[0], "source": r[1], "symbol": r[2], "headline": r[3],
             "summary": r[4], "url": r[5], "timestamp": r[6]}
            for r in rows
        ]

    def mark_analysis_complete(self, news_id, impact_score, sentiment, trigger=None, perspective=None, alerted=False):
        """v1.0: Updates a news item as Analyzed (status=1) or Alerted (status=2)."""
        status = 2 if alerted else 1
        try:
            with self.lock:
                with self.conn:
                    self.conn.execute(
                        """UPDATE news_items
                           SET processing_status = ?, impact_score = ?, sentiment = ?, trigger = ?, perspective = ?
                           WHERE id = ?""",
                        (status, impact_score, sentiment, trigger, perspective, news_id)
                    )
        except Exception as e:
            logger.error(f"Error marking analysis complete for {news_id}: {e}")

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

    def save_user(self, chat_id, first_name, username, source='direct'):
        """Saves a user and credits a 2-day free trial for first-time registrations (v1.3.1)."""
        with self.conn:
            # Check if user already exists
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, is_trial_used FROM users WHERE id = ?", (str(chat_id),))
            user = cursor.fetchone()
            
            if not user:
                # New user: Give 2 free market days
                logger.info(f"ðŸ†• NEW USER REGISTERED: {first_name} ({chat_id}) | Source: {source} | Credited 2-day trial.")
                self.conn.execute("""
                    INSERT INTO users (id, first_name, username, working_days_left, is_trial_used, is_active, source_tag)
                    VALUES (?, ?, ?, 2, 1, 1, ?)
                """, (str(chat_id), first_name, username, source))
                return True # New registration
            return False

    
    def ensure_user(self, chat_id):
        """Ensure a user row exists without overwriting names."""
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO users (id, first_name, username, is_active, working_days_left)
                   VALUES (?, 'User', '', 0, 0)""",
                (str(chat_id),)
            )

    def cleanup_legacy_names(self):
        """Normalize placeholder names so UI doesn't show Sync_Legacy."""
        with self.conn:
            self.conn.execute(
                "UPDATE users SET first_name = 'User' WHERE first_name IN ('Sync_Legacy','Legacy','manual_entry','Unknown')"
            )

    def get_user_count(self):
        """Returns the total number of unique users."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]

    def add_working_days(self, chat_id, days, reason="Manual Grant / Payment"):
        """Credits a user with Market Days and activates them (UPSERT)."""
        with self.conn:
            # 1. Fetch old balance for audit
            cursor = self.conn.cursor()
            cursor.execute("SELECT working_days_left FROM users WHERE id = ?", (str(chat_id),))
            old_row = cursor.fetchone()
            old_balance = old_row[0] if old_row else 0

            # 2. Ensure user exists (fallback registration)
            self.conn.execute("""
                INSERT OR IGNORE INTO users (id, first_name, username, is_active, working_days_left)
                VALUES (?, 'Manual', 'manual_entry', 1, 0)
            """, (str(chat_id),))
            
            # 3. Update days
            self.conn.execute("""
                UPDATE users 
                SET working_days_left = working_days_left + ?, 
                    is_active = 1 
                WHERE id = ?
            """, (days, str(chat_id)))

            # 4. Log the "CREDIT" for Hisab audit (v1.3)
            new_balance = old_balance + days
            self.conn.execute("""
                INSERT INTO user_billing_log (chat_id, event_type, amount, reason, balance_after)
                VALUES (?, 'CREDIT', ?, ?, ?)
            """, (str(chat_id), days, reason, new_balance))
            
            logger.info(f"Billing Hub: Credited {days} days to {chat_id} | New Bal: {new_balance}")

    def decrement_working_days(self, reason="Trading Day Deduction"):
        """Decrements 1 day from all active users and logs the event (v2.0)."""
        with self.conn:
            # 1. Fetch users to log before decrementing
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, working_days_left FROM users WHERE working_days_left > 0 AND is_active = 1")
            active_users = cursor.fetchall()

            if not active_users:
                return

            # 2. Decrement days
            self.conn.execute("UPDATE users SET working_days_left = working_days_left - 1 WHERE working_days_left > 0 AND is_active = 1")
            
            # 3. Deactivate users with 0 days left
            self.conn.execute("UPDATE users SET is_active = 0 WHERE working_days_left <= 0")

            # 4. Log the "Hisab" (Accounting)
            for uid, old_balance in active_users:
                new_balance = old_balance - 1
                self.conn.execute("""
                    INSERT INTO user_billing_log (chat_id, event_type, amount, reason, balance_after)
                    VALUES (?, 'DEBIT', 1, ?, ?)
                """, (uid, reason, new_balance))
                
            logger.info(f"Billing Hub: Successfully processed 'Hisab' for {len(active_users)} users | Reason: {reason}")

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
        """Fetches users with exactly 1 day left â€” for 24h pre-expiry reminders."""
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

    def get_all_users(self, limit=20, offset=0):
        """Fetches registered users with status and pagination (v12.0)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, first_name, username, is_active, working_days_left FROM users ORDER BY registered_at DESC LIMIT ? OFFSET ?", 
            (limit, offset)
        )
        return cursor.fetchall()

    def get_user_payment_history(self, chat_id):
        """Fetches successful payments for a specific user (v12.0)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT link_id, days, created_at FROM payment_links WHERE chat_id = ? AND status = 'processed' ORDER BY created_at DESC", 
            (str(chat_id),)
        )
        return cursor.fetchall()

    def get_billing_logs(self, chat_id, limit=5):
        """v2.0: Fetches the 'Hisab' audit trail for a user."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT event_type, amount, reason, balance_after, created_at FROM user_billing_log WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
            (str(chat_id), limit)
        )
        return cursor.fetchall()

    def get_global_hisab(self, days=1):
        """v2.0: Summary of all billing events for Admin audit."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT SUM(amount) FROM user_billing_log 
            WHERE event_type='DEBIT' AND created_at > datetime('now', ?)
        """, (f"-{days} days",))
        total_debits = cursor.fetchone()[0] or 0
        
        cursor.execute("""
            SELECT COUNT(DISTINCT chat_id) FROM user_billing_log 
            WHERE event_type='DEBIT' AND created_at > datetime('now', ?)
        """, (f"-{days} days",))
        unique_users = cursor.fetchone()[0] or 0
        
        return total_debits, unique_users

    def get_config(self, key, default=None):
        """v2.0: Fetches live system config from DB."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM system_config WHERE key = ?", (key,))
        res = cursor.fetchone()
        return res[0] if res else default

    def set_config(self, key, value):
        """v2.0: Updates live system config."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, str(value))
            )

    # â”€â”€ v2.0: Admin Session Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def set_admin_session(self, chat_id):
        """Creates or updates a persistent admin session."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO admin_sessions (chat_id, last_activity) VALUES (?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(chat_id) DO UPDATE SET last_activity = excluded.last_activity",
                (str(chat_id),)
            )

    def get_users_by_remaining_days(self, days):
        """v4.3: Fetches users for trial expiry nudges."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users WHERE working_days_left = ?", (days,))
        return [row[0] for row in cursor.fetchall()]

    def get_daily_funnel(self):
        """v4.3: High-visibility Conversion Metrics for Admins."""
        cursor = self.conn.cursor()
        
        # New users today
        cursor.execute("SELECT COUNT(*) FROM users WHERE date(registered_at) = date('now', 'localtime')")
        new_users = cursor.fetchone()[0]
        
        # Trial active users
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1 AND working_days_left > 0")
        active_trials = cursor.fetchone()[0]
        
        # Total dispatches today
        cursor.execute("SELECT COUNT(*) FROM alert_dispatch_log WHERE date(dispatch_time) = date('now', 'localtime')")
        signals = cursor.fetchone()[0]
        
        return {
            "new_users": new_users,
            "active_trials": active_trials,
            "signals_today": signals
        }

    def is_admin_session_valid(self, chat_id, timeout_minutes=43200):
        """Checks if an admin session is still valid."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT last_activity FROM admin_sessions WHERE chat_id = ? AND "
            "strftime('%s', 'now') - strftime('%s', last_activity) < ?",
            (str(chat_id), int(timeout_minutes) * 60)
        )
        return cursor.fetchone() is not None

    def clear_admin_session(self, chat_id):
        """Removes an admin session on logout."""
        with self.conn:
            self.conn.execute("DELETE FROM admin_sessions WHERE chat_id = ?", (str(chat_id),))

    def get_all_admin_sessions(self):
        """Returns all active admin chat IDs."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT chat_id FROM admin_sessions")
        return [row[0] for row in cursor.fetchall()]

    def purge_old_data(self, days=30):
        """v1.3: Deletes news items older than N days to save space on 1GB VPS."""
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM news_items WHERE created_at < datetime('now', ?)",
                (f"-{days} days",)
            )
            deleted_news = cursor.rowcount
            
            # Also purge old logs to keep it lean
            cursor = self.conn.execute(
                "DELETE FROM user_billing_log WHERE created_at < datetime('now', ?)",
                (f"-{days*2} days",) # Keep logs longer for support
            )
            deleted_logs = cursor.rowcount
            
            logger.info(f"ðŸ§¹ Hygiene: Purged {deleted_news} old news items and {deleted_logs} logs.")
            return deleted_news

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

    def get_recent_analyzed_news(self, hours=18, min_score=1):
        """v4.0: Fetches specifically analyzed context for summarizing reports (Filtered)."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT id, headline, summary, impact_score, url, source, symbol 
               FROM news_items 
               WHERE created_at > datetime('now', ?) 
               AND processing_status IN (1, 2) 
               AND impact_score >= ? 
               AND impact_score IS NOT NULL
               ORDER BY impact_score DESC, created_at DESC""",
            (f"-{hours} hours", min_score)
        )
        return [{"id": row[0], "headline": row[1], "summary": row[2], "impact_score": row[3], "url": row[4], "source": row[5], "symbol": row[6]} for row in cursor.fetchall()]

    def get_all_user_ids(self):
        """v4.0: Returns all chat IDs for cache reconciliation on boot."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users")
        return [row[0] for row in cursor.fetchall()]

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

    def run_maintenance(self):
        """v16.0: Automated DB optimization and cleanup."""
        try:
            logger.info("Starting Database Maintenance Cycle...")
            with self.conn:
                # 1. Integrity Check
                cursor = self.conn.execute("PRAGMA integrity_check")
                res = cursor.fetchone()[0]
                if res != "ok":
                    logger.critical(f"DATABASE INTEGRITY FAILED: {res}")
                    return False
                
                # 2. Delete news older than 30 days (Rule #14: RAM optimization)
                self.conn.execute("DELETE FROM news_items WHERE created_at < datetime('now', '-30 days')")
                deleted = self.conn.execute("SELECT changes()").fetchone()[0]
                
                # 3. Optimize storage
                self.conn.execute("VACUUM")
                self.conn.execute("ANALYZE")
                
            logger.info(f"DB Maintenance Complete. Purged {deleted} old items. Status: Healthy")
            return True
        except Exception as e:
            logger.error(f"DB Maintenance Error: {e}")
            return False

    def backup(self):
        """v1.3.3: Performs a consistent online backup of the institutional database."""
        backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"pulse_backup_{timestamp}.db")
        
        try:
            # Use SQLite's online backup API for a clean snapshot (Safe for WAL mode)
            with sqlite3.connect(backup_file) as backup_conn:
                self.conn.backup(backup_conn)
            
            # Update last backup time (Persistent)
            self.set_config("last_backup", str(time.time()))
            logger.info(f"âœ… Institutional Backup Complete: {os.path.basename(backup_file)}")
            
            # Clean up old backups (keep last 5)
            backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".db")])
            if len(backups) > 5:
                for b in backups[:-5]:
                    os.remove(b)
            return True
        except Exception as e:
            logger.error(f"âŒ Database backup failure: {e}")
            return False

    def needs_backup(self):
        """Returns True if last backup was > 24 hours ago."""
        try:
            last_ts = float(self.get_config("last_backup") or 0)
            return (time.time() - last_ts) > 86400
        except:
            return True

    def get_news_by_id(self, news_id):
        """v4.3.1: Fetches a single news item by its database ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM news_items WHERE id = ?", (news_id,))
        row = cursor.fetchone()
        if not row: return None
        return {
            "id": row[0], "source": row[1], "symbol": row[2], 
            "headline": row[3], "summary": row[4], "url": row[5],
            "impact_score": row[10], "sentiment": row[11]
        }

