import sqlite3
import os
import glob
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
            # v8.0: Increased cache for 2GB VPS
            self.conn.execute("PRAGMA cache_size = -8192")
            # Test connection immediately
            self.conn.execute("SELECT 1")
            self._create_table()
            self._migrate_schema()
        except sqlite3.DatabaseError as e:
            if "malformed" in str(e).lower():
                logger.error(f"â Œ DATABASE CORRUPTED: {e}. Initiating auto-rescue...")
                self._handle_malformed()
            else:
                raise e

    def _handle_malformed(self):
        """v2.1: Rescues the system from a 'malformed' error with mandatory backup checks (Option E)."""
        import shutil
        import sys
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{DB_PATH}.malformed_{timestamp}.bak"
        
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
            
            # 1. Preserve the corrupted DB as a diagnostic copy
            shutil.move(DB_PATH, backup_path)
            logger.warning(f"🚨 DATABASE CORRUPTED: Original moved to {backup_path}")

            # 2. Attempt restoration from the dedicated 'backups/' directory
            if self._restore_latest_backup():
                self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
                self.lock = threading.Lock()
                self._create_table()
                self._migrate_schema()
                logger.info("✅ Database successfully restored from recent backup.")
                return

            # 3. CRITICAL: Halt rather than auto-resetting if no backups exist.
            # This prevents silent data loss for users and billing logs.
            logger.critical("🔥 FATAL: Database corrupted and NO healthy backups found in 'backups/' folder.")
            logger.critical("SYSTEM HALTED. Manual intervention required to prevent data loss.")
            
            # Attempt a minimal alert if the bot instance is accessible (rare in this state)
            # but we assume the main.py watchdog or systemd will detect this exit.
            sys.exit(1)

        except Exception as ex:
            logger.critical(f"🔥 FATAL: Database recovery logic failed: {ex}")
            sys.exit(1)

    def _restore_latest_backup(self):
        """Restores DB_PATH from the newest valid backup snapshot, if available."""
        import shutil
        backup_dir = os.path.join(os.path.dirname(DB_PATH), "backups")
        candidates = sorted(glob.glob(os.path.join(backup_dir, "pulse_backup_*.db")), reverse=True)

        for candidate in candidates:
            try:
                with sqlite3.connect(candidate) as test_conn:
                    status = test_conn.execute("PRAGMA integrity_check").fetchone()[0]
                    if status != "ok":
                        continue

                    has_users = test_conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
                    ).fetchone()
                    if not has_users:
                        continue

                shutil.copy2(candidate, DB_PATH)
                logger.warning(f"âš ï¸ Restored database from backup: {candidate}")
                return True
            except Exception as ex:
                logger.warning(f"Backup candidate rejected ({candidate}): {ex}")

        logger.error("No valid backup found for malformed DB auto-restore.")
        return False

    def _create_table(self):
        with self.conn:
            # v3.1: WAL + NORMAL sync. NORMAL is safe with WAL; eliminates disk flush per write (~50x faster on VPS).
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
                    plan_amount INTEGER DEFAULT 0,
                    payable_amount INTEGER DEFAULT 0,
                    discount_percent INTEGER DEFAULT 0,
                    discount_rupees INTEGER DEFAULT 0,
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

            # Runtime symbol cooldown store (DB-backed to reduce in-memory state).
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS symbol_cooldowns (
                    symbol TEXT PRIMARY KEY,
                    last_alert_ts REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Initial Config Seeds (v6.8: Institutional Policy 8/10)
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('ai_threshold', '8')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('media_mute', '0')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('last_backup', '0')")

            # v8.0: Referral + Free Trial config seeds
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('free_trial_enabled', '0')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('referral_reward_percent', '10')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('direct_trial_days', '0')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('referral_trial_days', '7')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('last_user_backup_sync_at', '0')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('last_referral_sync_at', '0')")
            self.conn.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('last_payment_sync_at', '0')")

            # v8.0: Referral Links table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id TEXT NOT NULL,
                    referral_code TEXT UNIQUE NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_referral_links_owner ON referral_links(owner_user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_referral_links_code ON referral_links(referral_code)")

            # v8.0: Referral Events table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_user_id TEXT NOT NULL,
                    referred_user_id TEXT NOT NULL,
                    referral_code TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    amount INTEGER DEFAULT 0,
                    metadata_json TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_events_referrer ON referral_events(referrer_user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_events_referred ON referral_events(referred_user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_events_created ON referral_events(created_at)")

            # v8.0: Referral Rewards Ledger table (immutable double-entry style)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_rewards_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    amount_rupees INTEGER NOT NULL,
                    reason TEXT,
                    related_user_id TEXT NULL,
                    related_payment_link_id TEXT NULL,
                    balance_after INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rewards_user ON referral_rewards_ledger(user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_rewards_created ON referral_rewards_ledger(created_at)")

            # v8.0: Referral Admin Actions audit table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS referral_admin_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_chat_id TEXT NOT NULL,
                    target_user_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    amount_rupees INTEGER DEFAULT 0,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_actions_target ON referral_admin_actions(target_user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_actions_created ON referral_admin_actions(created_at)")

            # v8.0: Supabase Sync Outbox (async mirror queue)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS supabase_sync_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    sync_status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_outbox_status ON supabase_sync_outbox(sync_status)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sync_outbox_entity ON supabase_sync_outbox(entity_type, entity_id)")

            

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
        # v6.9: Mandatory Threshold Sanitation (Institutional Policy)
        # Forcefully upgrade legacy '5' to '8' to prevent stale overrides.
        with self.conn:
            self.conn.execute("UPDATE system_config SET value = '8' WHERE key = 'ai_threshold' AND value = '5'")

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

        # v8.0: Referral + payment tracking columns
        for col, col_type in [
            ("referral_code", "TEXT"),
            ("referred_by_code", "TEXT"),
            ("referred_by_user_id", "TEXT"),
            ("trial_days_granted", "INTEGER DEFAULT 0"),
            ("first_paid_at", "TIMESTAMP"),
            ("total_paid_amount", "INTEGER DEFAULT 0"),
        ]:
            if col not in user_cols:
                try:
                    with self.conn:
                        self.conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                        logger.info(f"Migration: Added {col} to users table.")
                except Exception as e:
                    logger.error(f"Migration failed (users.{col}): {e}")

        # v8.0: Indexes for referral lookups
        with self.conn:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by_user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active)")

        # Table: payment_links (additive metadata for admin-controlled plan discount)
        cursor.execute("PRAGMA table_info(payment_links)")
        pay_cols = [row[1] for row in cursor.fetchall()]
        for col, col_type in [
            ("plan_amount", "INTEGER DEFAULT 0"),
            ("payable_amount", "INTEGER DEFAULT 0"),
            ("discount_percent", "INTEGER DEFAULT 0"),
            ("discount_rupees", "INTEGER DEFAULT 0"),
        ]:
            if col not in pay_cols:
                try:
                    with self.conn:
                        self.conn.execute(f"ALTER TABLE payment_links ADD COLUMN {col} {col_type}")
                        logger.info(f"Migration: Added {col} to payment_links.")
                except Exception as e:
                    logger.error(f"Migration failed (payment_links.{col}): {e}")


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

    def is_content_duplicate(self, headline, content_hash, symbol=None):
        """Checks if content is duplicate based on Hash OR Headline."""
        cursor = self.conn.cursor()
        
        # 1. Content Hash Check (Global Exact Match)
        if content_hash:
            cursor.execute("SELECT id FROM news_items WHERE content_hash = ?", (content_hash,))
            if cursor.fetchone(): return True
        
        # 2. Headline Check (Headline + Symbol Match within 48 hours to allow recurring reports)
        if headline and symbol:
            cursor.execute(
                "SELECT id FROM news_items WHERE headline = ? AND symbol = ? AND created_at > datetime('now', '-2 days')", 
                (headline, symbol)
            )
            if cursor.fetchone(): return True
        elif headline:
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

    def claim_pending_news(self, limit=4):
        """Atomically claims pending items for processing (status: 0 -> 9)."""
        with self.lock:
            with self.conn:
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
                if not rows:
                    return []

                ids = [r[0] for r in rows]
                placeholders = ",".join(["?"] * len(ids))
                self.conn.execute(
                    f"UPDATE news_items SET processing_status = 9 WHERE id IN ({placeholders})",
                    ids
                )

                return [
                    {"db_id": r[0], "source": r[1], "symbol": r[2], "headline": r[3],
                     "summary": r[4], "url": r[5], "timestamp": r[6]}
                    for r in rows
                ]

    def set_processing_status(self, news_id, status):
        """Direct status update for recovery paths (e.g., retry on processor failure)."""
        try:
            with self.lock:
                with self.conn:
                    self.conn.execute(
                        "UPDATE news_items SET processing_status = ? WHERE id = ?",
                        (int(status), news_id)
                    )
        except Exception as e:
            logger.error(f"Error setting processing status for {news_id}: {e}")

    def reset_inflight_news(self):
        """Recovers in-flight claimed items (status=9) back to pending after restart/crash."""
        try:
            with self.lock:
                with self.conn:
                    self.conn.execute(
                        "UPDATE news_items SET processing_status = 0 WHERE processing_status = 9"
                    )
                    recovered = self.conn.execute("SELECT changes()").fetchone()[0]
            if recovered:
                logger.warning("Recovered %s in-flight news items back to pending queue.", recovered)
            return recovered
        except Exception as e:
            logger.error(f"Failed to recover in-flight news: {e}")
            return 0

    def expire_stale_pending_news(self, max_age_hours=4):
        """v3.1: Discard stale pending items (older than N hours), score=0, no LLM.
        Prevents multi-hour backlog from blocking fresh market news on each cycle."""
        try:
            with self.lock:
                with self.conn:
                    self.conn.execute(
                        "UPDATE news_items SET processing_status=1, impact_score=0, sentiment=?"
                        " WHERE processing_status=0 AND created_at < datetime('now', '-'||?||' hours')",
                        ("Expired", str(int(max_age_hours)))
                    )
                    count = self.conn.execute("SELECT changes()").fetchone()[0]
            if count:
                logger.info("Stale Pruner: %s items expired (>%sh old).", count, max_age_hours)
            return count
        except Exception as e:
            logger.error("Stale Pruner failed: %s", e)
            return 0

    def get_symbol_last_alert_ts(self, symbol):
        """Returns last alert unix ts for a symbol from DB-backed cooldown store."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT last_alert_ts FROM symbol_cooldowns WHERE symbol = ?",
            (str(symbol).upper(),)
        )
        row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def set_symbol_cooldown(self, symbol, ts=None):
        """Upserts symbol cooldown timestamp in DB."""
        ts = float(ts if ts is not None else time.time())
        with self.lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO symbol_cooldowns (symbol, last_alert_ts, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(symbol) DO UPDATE SET last_alert_ts = excluded.last_alert_ts, updated_at = excluded.updated_at",
                    (str(symbol).upper(), ts)
                )

    def clear_symbol_cooldowns(self):
        """Clears cooldown table, used during daily reset."""
        with self.lock:
            with self.conn:
                self.conn.execute("DELETE FROM symbol_cooldowns")

    def mark_analysis_complete(self, news_id, impact_score, sentiment, trigger=None, perspective=None, alerted=False, status=None):
        """v1.0: Updates a news item as Analyzed (status=1) or Alerted (status=2) or Queued (status=3)."""
        if status is None:
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

    def save_user(self, chat_id, first_name, username, source='direct', referral_code: str = None, referred_by_user_id: str = None):
        """Saves a user and credits trial (if toggle ON). Handles referral attribution (v8.0)."""
        with self.conn:
            # Check if user already exists
            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM users WHERE id = ?", (str(chat_id),))
            user = cursor.fetchone()
            
            if not user:
                # New user: Check free-trial toggle
                trial_enabled = int(self.get_config("free_trial_enabled", "0"))
                trial_days_to_grant = int(self.get_config("referral_trial_days", "7")) if referral_code else int(self.get_config("direct_trial_days", "0"))
                working_days = trial_days_to_grant if trial_enabled else 0
                is_active = 1 if working_days > 0 else 0
                
                logger.info(f"🆕 NEW USER REGISTERED: {first_name} ({chat_id}) | Source: {source} | Trial: {working_days} days")
                
                self.conn.execute("""
                    INSERT INTO users (id, first_name, username, working_days_left, is_active, source_tag, 
                                       referred_by_code, referred_by_user_id, trial_days_granted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(chat_id), first_name, username, working_days, is_active, source, referral_code, str(referred_by_user_id) if referred_by_user_id else None, working_days))
                
                # Generate and assign referral code for new user
                self.create_referral_code(str(chat_id))
                
                # Record referral event if applicable
                if referral_code and referred_by_user_id:
                    self.save_referral_event(
                        referrer_user_id=str(referred_by_user_id),
                        referred_user_id=str(chat_id),
                        referral_code=referral_code,
                        event_type="signup"
                    )
                
                # Sync to Supabase outbox
                self.add_sync_outbox_row("users", str(chat_id), {
                    "id": str(chat_id),
                    "first_name": first_name,
                    "username": username,
                    "source_tag": source,
                    "trial_days_granted": working_days
                })
                
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
            # v8.0: Sync to Outbox on update
            self.add_sync_outbox_row("users", chat_id, {
                "id": str(chat_id), "first_name": first_name, "username": username
            })

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

    def is_admin_session_valid(self, chat_id, timeout_minutes=60):
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
               AND processing_status IN (1, 2, 3) 
               AND impact_score >= ? 
               AND impact_score IS NOT NULL
               ORDER BY impact_score DESC, created_at DESC""",
            (f"-{hours} hours", min_score)
        )
        return [{"id": row[0], "headline": row[1], "summary": row[2], "impact_score": row[3], "url": row[4], "source": row[5], "symbol": row[6]} for row in cursor.fetchall()]

    def get_queued_news(self, hours=72):
        """v5.0: Fetches news that was analyzed and qualified but queued (status=3). Use for morning dispatch."""
        cursor = self.conn.cursor()
        # Fetch status=3 (Qualified and Queued)
        cursor.execute(
            """SELECT id, headline, summary, impact_score, url, source, symbol, sentiment, trigger, perspective
               FROM news_items 
               WHERE created_at > datetime('now', ?) 
               AND processing_status = 3
               ORDER BY created_at ASC""",
            (f"-{hours} hours",)
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row[0], "headline": row[1], "summary": row[2], 
                "impact_score": row[3], "url": row[4], "source": row[5], 
                "symbol": row[6], "sentiment": row[7], "trigger": row[8],
                "perspective": row[9]
            } 
            for row in rows
        ]

    def get_pending_news_count(self):
        """v2.0: Returns the number of news items waiting for AI processing (status=0)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM news_items WHERE processing_status = 0")
        return cursor.fetchone()[0]


    def get_all_user_ids(self):
        """v4.0: Returns all chat IDs for cache reconciliation on boot."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users")
        return [row[0] for row in cursor.fetchall()]

    def save_payment_link(self, link_id, chat_id, days, plan_amount=0, payable_amount=0,
                          discount_percent=0, discount_rupees=0):
        """Stores a new payment link for background polling (Rule #24)."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO payment_links
                   (link_id, chat_id, days, plan_amount, payable_amount, discount_percent, discount_rupees, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (link_id, str(chat_id), days, int(plan_amount or 0), int(payable_amount or 0), int(discount_percent or 0), int(discount_rupees or 0))
            )

    def get_pending_payment_links(self):
        """Fetches all links that haven't been confirmed as paid yet."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT link_id, chat_id, days, plan_amount, payable_amount, discount_percent, discount_rupees
               FROM payment_links WHERE status = 'pending'"""
        )
        return cursor.fetchall()

    def get_payment_link_meta(self, link_id):
        """Returns payment metadata for a link: plan, payable and discount fields."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT plan_amount, payable_amount, discount_percent, discount_rupees
               FROM payment_links WHERE link_id = ?""",
            (str(link_id),)
        )
        row = cursor.fetchone()
        if not row:
            return {"plan_amount": 0, "payable_amount": 0, "discount_percent": 0, "discount_rupees": 0}
        return {
            "plan_amount": int(row[0] or 0),
            "payable_amount": int(row[1] or 0),
            "discount_percent": int(row[2] or 0),
            "discount_rupees": int(row[3] or 0),
        }

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
            
            # Clean up old backups (keep last 30 restore points)
            backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".db")])
            if len(backups) > 30:
                for b in backups[:-30]:
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

    def get_last_signals(self, limit=10):
        """FR-01: Returns last N dispatched signals for /signals command."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT a.symbol, a.score, a.sentiment, a.trigger_class, a.dispatch_time, n.headline, n.url
            FROM alert_dispatch_log a
            LEFT JOIN news_items n ON a.news_id = n.id
            ORDER BY a.dispatch_time DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [
            {
                "symbol": r[0],
                "score": r[1],
                "sentiment": r[2],
                "trigger": r[3],
                "dispatch_time": r[4],
                "headline": r[5],
                "url": r[6]
            }
            for r in rows
        ]

    # ── v8.0: Free Trial Toggle ────────────────────────────────────────────────

    def is_free_trial_enabled(self):
        """Returns True if the admin-panel free-trial toggle is ON."""
        return self.get_config("free_trial_enabled", "0") == "1"

    def set_free_trial_enabled(self, enabled: bool, admin_chat_id: str = "system"):
        """Flips the free-trial toggle and writes an audit row."""
        value = "1" if enabled else "0"
        self.set_config("free_trial_enabled", value)
        label = "ON" if enabled else "OFF"
        with self.conn:
            self.conn.execute(
                """INSERT INTO referral_admin_actions
                   (admin_chat_id, target_user_id, action_type, amount_rupees, note)
                   VALUES (?, 'SYSTEM', 'free_trial_toggle', 0, ?)""",
                (str(admin_chat_id), f"Free trial toggled {label}")
            )
        logger.info(f"Free trial toggle set to {label} by admin {admin_chat_id}")

    def get_direct_trial_days(self):
        """Returns configured trial days for direct (non-referred) users."""
        return int(self.get_config("direct_trial_days", "0"))

    def get_referral_trial_days(self):
        """Returns configured trial days for referred users."""
        return int(self.get_config("referral_trial_days", "7"))

    # ── v8.0: Referral Code Management ────────────────────────────────────────

    def create_referral_code(self, user_id: str) -> str:
        """Generates and stores a unique referral code for a user. Returns the code."""
        # Phase 3: Format RB + last 5 digits of ID
        suffix = str(user_id)[-5:]
        code = f"RB{suffix}"
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE users SET referral_code = ? WHERE id = ? AND referral_code IS NULL",
                    (code, str(user_id))
                )
                self.conn.execute(
                    "INSERT OR IGNORE INTO referral_links (owner_user_id, referral_code) VALUES (?, ?)",
                    (str(user_id), code)
                )
            logger.info(f"Referral code created: {code} for user {user_id}")
        except Exception as e:
            logger.error(f"create_referral_code failed for {user_id}: {e}")
        return code

    def get_referral_code(self, user_id: str):
        """Returns user's referral_code, creating one if missing."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT referral_code FROM users WHERE id = ?", (str(user_id),))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
        return self.create_referral_code(user_id)

    def get_user_id_by_referral_code(self, code: str):
        """Looks up the owner user_id for a referral code. Returns None if not found."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT owner_user_id FROM referral_links WHERE referral_code = ? AND is_active = 1",
            (code.upper(),)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_referral_attribution(self, user_id: str, referral_code: str, referrer_user_id: str):
        """Saves referral attribution on a user row (first-touch, never overwritten)."""
        if str(user_id) == str(referrer_user_id):
            return
        with self.conn:
            self.conn.execute(
                """UPDATE users
                   SET referred_by_code = ?, referred_by_user_id = ?
                   WHERE id = ? AND referred_by_code IS NULL""",
                (referral_code, str(referrer_user_id), str(user_id))
            )

    # ── v8.0: Referral Events ─────────────────────────────────────────────────

    def save_referral_event(self, referrer_user_id: str, referred_user_id: str,
                            referral_code: str, event_type: str,
                            amount: int = 0, metadata: dict = None):
        """Inserts a referral event row. event_type: signup|trial_started|converted|reward_credited|reward_redeemed|trial_skipped|invalid_referral"""
        import json
        meta_str = json.dumps(metadata) if metadata else None
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO referral_events
                       (referrer_user_id, referred_user_id, referral_code, event_type, amount, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(referrer_user_id), str(referred_user_id), referral_code, event_type, amount, meta_str)
                )
                # v8.0: Sync to Outbox
                self.add_sync_outbox_row("referral_events", f"{referrer_user_id}_{referred_user_id}_{int(time.time())}", {
                    "referrer_user_id": str(referrer_user_id),
                    "referred_user_id": str(referred_user_id),
                    "referral_code": referral_code,
                    "event_type": event_type,
                    "amount": amount
                })
        except Exception as e:
            logger.error(f"save_referral_event failed ({event_type}): {e}")

    def get_referral_stats(self, referrer_user_id: str) -> dict:
        """Returns referral metrics for a user: joins, conversions, reward_balance."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM referral_events WHERE referrer_user_id = ? AND event_type = 'signup'",
            (str(referrer_user_id),)
        )
        joins = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM referral_events WHERE referrer_user_id = ? AND event_type = 'converted'",
            (str(referrer_user_id),)
        )
        conversions = cursor.fetchone()[0]

        balance = self.get_reward_balance(referrer_user_id)
        return {"joins": joins, "conversions": conversions, "reward_balance": balance}

    def get_referred_users(self, referrer_user_id: str):
        """Returns list of (user_id, first_name, is_active, total_paid_amount) referred by this user."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT u.id, u.first_name, u.is_active, u.total_paid_amount, u.registered_at
               FROM users u
               WHERE u.referred_by_user_id = ?
               ORDER BY u.registered_at DESC""",
            (str(referrer_user_id),)
        )
        return cursor.fetchall()

    def get_all_referred_users(self, limit=50, offset=0):
        """Admin view: all users who were referred (have a referred_by_code)."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT id, first_name, username, is_active, working_days_left,
                      referred_by_code, total_paid_amount, registered_at
               FROM users WHERE referred_by_code IS NOT NULL
               ORDER BY registered_at DESC LIMIT ? OFFSET ?""",
            (limit, offset)
        )
        return cursor.fetchall()

    def get_referred_users_filtered(self, mode="all", limit=50, offset=0):
        """Admin view: referred users with filter buckets."""
        cursor = self.conn.cursor()
        where = "WHERE referred_by_code IS NOT NULL"
        params = []

        if mode == "converted":
            where += " AND total_paid_amount > 0"
        elif mode == "non_converted":
            where += " AND total_paid_amount <= 0"
        elif mode == "pending_trial":
            where += " AND is_active = 1 AND working_days_left BETWEEN 1 AND 2"

        query = f"""SELECT id, first_name, username, is_active, working_days_left,
                           referred_by_code, total_paid_amount, registered_at
                    FROM users
                    {where}
                    ORDER BY registered_at DESC LIMIT ? OFFSET ?"""
        params.extend([limit, offset])
        cursor.execute(query, tuple(params))
        return cursor.fetchall()

    def get_referrer_leaderboard(self, limit=20):
        """Admin view: top referrers by total conversions."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT referrer_user_id,
                      COUNT(CASE WHEN event_type='signup' THEN 1 END) as joins,
                      COUNT(CASE WHEN event_type='converted' THEN 1 END) as conversions,
                      SUM(CASE WHEN event_type='converted' THEN amount ELSE 0 END) as paid_amount
               FROM referral_events
               GROUP BY referrer_user_id
               ORDER BY conversions DESC, joins DESC
               LIMIT ?""",
            (limit,)
        )
        return cursor.fetchall()

    # ── v8.0: Reward Ledger ───────────────────────────────────────────────────

    def get_reward_balance(self, user_id: str) -> int:
        """Returns current reward wallet balance (rupees) for a user."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT balance_after FROM referral_rewards_ledger WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (str(user_id),)
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def add_reward_ledger_entry(self, user_id: str, entry_type: str, amount_rupees: int,
                                reason: str = "", related_user_id: str = None,
                                related_payment_link_id: str = None) -> int:
        """Appends an immutable ledger entry. Returns new balance. entry_type: credit|debit|expire|adjust"""
        current = self.get_reward_balance(user_id)
        if entry_type == "debit":
            new_balance = max(0, current - amount_rupees)
            actual_debit = current - new_balance
        elif entry_type == "credit":
            new_balance = current + amount_rupees
            actual_debit = amount_rupees
        else:
            new_balance = max(0, current + amount_rupees)
            actual_debit = amount_rupees

        with self.conn:
            self.conn.execute(
                """INSERT INTO referral_rewards_ledger
                   (user_id, entry_type, amount_rupees, reason, related_user_id, related_payment_link_id, balance_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(user_id), entry_type, actual_debit, reason, related_user_id, related_payment_link_id, new_balance)
            )
        logger.info(f"Reward ledger: {entry_type} ₹{actual_debit} for {user_id} → balance ₹{new_balance}")
        return new_balance

    def log_referral_admin_action(self, admin_chat_id: str, target_user_id: str,
                                  action_type: str, amount_rupees: int = 0, note: str = ""):
        """Writes an audit row for every admin referral action."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO referral_admin_actions
                   (admin_chat_id, target_user_id, action_type, amount_rupees, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(admin_chat_id), str(target_user_id), action_type, amount_rupees, note)
            )

    def get_user_discount_percent(self, user_id: str) -> int:
        """Returns admin-approved one-time discount percent for next plan purchase."""
        key = f"user_discount_percent_{str(user_id)}"
        try:
            pct = int(self.get_config(key, "0") or "0")
        except Exception:
            pct = 0
        return max(0, min(95, pct))

    def set_user_discount_percent(self, user_id: str, percent: int, admin_chat_id: str = "system"):
        """Sets one-time discount percent for a user (consumed on successful payment)."""
        pct = max(0, min(95, int(percent or 0)))
        key = f"user_discount_percent_{str(user_id)}"
        self.set_config(key, str(pct))
        action = "discount_approved" if pct > 0 else "discount_rejected"
        note = f"One-time plan discount set to {pct}%"
        self.log_referral_admin_action(admin_chat_id, user_id, action_type=action, amount_rupees=0, note=note)

    def clear_user_discount_percent(self, user_id: str):
        """Clears user one-time discount after successful payment settlement."""
        key = f"user_discount_percent_{str(user_id)}"
        self.set_config(key, "0")

    # ── v8.0: Payment Attribution ─────────────────────────────────────────────

    def record_first_payment(self, user_id: str, amount: int, link_id: str = None):
        """Sets first_paid_at (once only) and accumulates total_paid_amount. Returns True if first payment."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT first_paid_at, total_paid_amount FROM users WHERE id = ?", (str(user_id),))
        row = cursor.fetchone()
        if not row:
            return False
        is_first = row[0] is None
        with self.conn:
            if is_first:
                self.conn.execute(
                    "UPDATE users SET first_paid_at = CURRENT_TIMESTAMP, total_paid_amount = total_paid_amount + ? WHERE id = ?",
                    (amount, str(user_id))
                )
            else:
                self.conn.execute(
                    "UPDATE users SET total_paid_amount = total_paid_amount + ? WHERE id = ?",
                    (amount, str(user_id))
                )

        # Mirror subscription event to Supabase outbox (non-blocking)
        event_id = f"sub_{str(link_id or int(time.time()))}_{str(user_id)}"
        self.add_sync_outbox_row("subscription_events", event_id, {
            "id": event_id,
            "user_id": str(user_id),
            "plan_amount": int(amount),
            "payment_status": "paid",
            "created_at": datetime.now(pytz.timezone('Asia/Kolkata')).isoformat()
        })
        return is_first

    def credit_referral_reward_on_conversion(self, referred_user_id: str, amount_paid: int, link_id: str = None):
        """Credits referrer's reward wallet (10% of first paid amount) if referral exists."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT referred_by_user_id FROM users WHERE id = ?", (str(referred_user_id),))
        row = cursor.fetchone()
        if not row or not row[0]:
            return
        referrer_id = row[0]
        reward_pct = int(self.get_config("referral_reward_percent", "10"))
        reward = max(1, (amount_paid * reward_pct) // 100)

        # v8.0: Log "converted" event first (payment confirmed)
        self.save_referral_event(
            referrer_user_id=referrer_id,
            referred_user_id=referred_user_id,
            referral_code=self.get_referral_code(referrer_id),
            event_type="converted",
            amount=amount_paid
        )

        # Then log reward credit
        self.add_reward_ledger_entry(
            referrer_id, "credit", reward,
            reason=f"Referral conversion: user {referred_user_id} paid ₹{amount_paid}",
            related_user_id=referred_user_id,
            related_payment_link_id=link_id
        )
        self.save_referral_event(
            referrer_user_id=referrer_id,
            referred_user_id=referred_user_id,
            referral_code=self.get_referral_code(referrer_id),
            event_type="reward_credited",
            amount=reward
        )

        # Mirror conversion event to Supabase outbox (for marketing/analytics read model)
        conv_id = f"conv_{str(referred_user_id)}_{int(time.time())}"
        self.add_sync_outbox_row("conversion_events", conv_id, {
            "id": conv_id,
            "referrer_user_id": str(referrer_id),
            "referred_user_id": str(referred_user_id),
            "paid_amount": int(amount_paid),
            "created_at": datetime.now(pytz.timezone('Asia/Kolkata')).isoformat()
        })

    # ── v8.0: Supabase Sync Outbox ────────────────────────────────────────────

    def add_sync_outbox_row(self, entity_type: str, entity_id: str, payload: dict):
        """Queues a row for async Supabase sync."""
        import json
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO supabase_sync_outbox
                       (entity_type, entity_id, payload_json, sync_status)
                       VALUES (?, ?, ?, 'pending')""",
                    (entity_type, str(entity_id), json.dumps(payload))
                )
        except Exception as e:
            logger.error(f"add_sync_outbox_row failed ({entity_type}/{entity_id}): {e}")

    def get_pending_sync_rows(self, limit=50, apply_backoff=False):
        """Returns pending outbox rows for the sync bridge to process."""
        cursor = self.conn.cursor()
        if apply_backoff:
            cursor.execute(
                """SELECT id, entity_type, entity_id, payload_json, retry_count
                   FROM supabase_sync_outbox
                   WHERE (
                        sync_status = 'pending'
                        OR (
                            sync_status = 'failed'
                            AND retry_count < 10
                            AND datetime(updated_at, '+' ||
                                CASE
                                    WHEN retry_count <= 1 THEN 1
                                    WHEN retry_count = 2 THEN 2
                                    WHEN retry_count = 3 THEN 4
                                    WHEN retry_count = 4 THEN 8
                                    ELSE 15
                                END
                            || ' minutes') <= CURRENT_TIMESTAMP
                        )
                   )
                   ORDER BY id ASC LIMIT ?""",
                (limit,)
            )
        else:
            cursor.execute(
                """SELECT id, entity_type, entity_id, payload_json, retry_count
                   FROM supabase_sync_outbox
                   WHERE sync_status IN ('pending', 'failed') AND retry_count < 10
                   ORDER BY id ASC LIMIT ?""",
                (limit,)
            )
        rows = cursor.fetchall()
        return [
            {"id": r[0], "entity_type": r[1], "entity_id": r[2],
             "payload_json": r[3], "retry_count": r[4]}
            for r in rows
        ]

    def mark_sync_row_done(self, row_id: int):
        """Marks an outbox row as successfully synced."""
        with self.conn:
            self.conn.execute(
                "UPDATE supabase_sync_outbox SET sync_status='synced', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row_id,)
            )

    def mark_sync_row_failed(self, row_id: int, error: str):
        """Increments retry count and stores last error for a failed outbox row."""
        with self.conn:
            self.conn.execute(
                """UPDATE supabase_sync_outbox
                   SET sync_status='failed', retry_count=retry_count+1,
                       last_error=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (str(error)[:500], row_id)
            )

    def get_users_for_supabase_mirror(self, since_ts: float = 0, limit: int = 200):
        """Returns user rows modified after since_ts for Supabase user-list backup."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT id, first_name, username, is_active, working_days_left,
                      referral_code, referred_by_code, trial_days_granted,
                      total_paid_amount, registered_at
               FROM users
               WHERE strftime('%s', registered_at) > ?
               ORDER BY registered_at ASC LIMIT ?""",
            (str(int(since_ts)), limit)
        )
        rows = cursor.fetchall()
        return [
            {
                "user_id": r[0], "first_name": r[1], "username": r[2],
                "is_active": r[3], "working_days_left": r[4],
                "referral_code": r[5], "referred_by_code": r[6],
                "trial_days_granted": r[7], "total_paid_amount": r[8],
                "registered_at": r[9]
            }
            for r in rows
        ]

    def backfill_supabase_outbox(self):
        """Phase 14: Queues all existing users into the Supabase sync outbox."""
        with self.lock:
            cursor = self.conn.execute("SELECT id, first_name, username, is_active, referral_code FROM users")
            users = cursor.fetchall()
            count = 0
            for u in users:
                uid, name, uname, active, ref_code = u
                payload = {
                    "id": str(uid),
                    "first_name": name,
                    "username": uname,
                    "is_active": active,
                    "referral_code": ref_code
                }
                self.add_sync_outbox_row("users", uid, payload)
                count += 1
            return count

