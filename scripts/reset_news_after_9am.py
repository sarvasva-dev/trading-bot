"""
reset_news_after_9am.py
-----------------------
Admin utility: Resets all news items captured after 09:00 AM IST today
back to 'Pending' (processing_status=0) so the bot reprocesses and
re-sends them via Telegram.

Usage (run from project root on VPS):
    python scripts/reset_news_after_9am.py
"""
import sqlite3
import os
import sys
import pytz
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Derived from config.py:
#   BASE_DIR = nse_monitor/ (dirname of config.py)
#   DB_PATH  = nse_monitor/data/processed_announcements.db
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_ROOT, 'nse_monitor', 'data', 'processed_announcements.db')


def reset_news_after_9am():
    logger.info(f"DB Path resolved: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        logger.error(f"[ERROR] Database not found at: {DB_PATH}")
        logger.error("Make sure you are running this from the nse2/ project root.")
        sys.exit(1)

    # 09:00 AM IST today → convert to UTC for SQLite comparison
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    target_ist = now_ist.replace(hour=9, minute=0, second=0, microsecond=0)
    target_utc = target_ist.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')

    logger.info(f"Target window : After {target_ist.strftime('%Y-%m-%d %H:%M:%S')} IST")
    logger.info(f"SQLite UTC cut: {target_utc}")
    logger.info("-" * 50)

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA busy_timeout = 10000")
        cursor = conn.cursor()

        # Step 1: Identify all news after 9 AM
        cursor.execute(
            "SELECT id, headline, processing_status FROM news_items WHERE created_at >= ?",
            (target_utc,)
        )
        news_items = cursor.fetchall()

        if not news_items:
            logger.info("No news items found after 9:00 AM IST. Nothing to reset.")
            return

        news_ids = [item[0] for item in news_items]
        logger.info(f"Found {len(news_ids)} news item(s) to requeue:\n")
        for item in news_items:
            status_label = {0: "Pending", 1: "Analyzed", 2: "Alerted", 3: "Queued"}.get(item[2], str(item[2]))
            logger.info(f"  [ID:{item[0]} | {status_label}] {item[1][:70]}")

        logger.info("\nResetting...")

        # Use parameterized placeholders — no f-string injection
        placeholders = ','.join('?' * len(news_ids))

        # Step 2: Clear AI analysis + reset status to Pending
        conn.execute(f"""
            UPDATE news_items
            SET processing_status  = 0,
                impact_score       = NULL,
                sentiment          = NULL,
                trigger            = NULL,
                perspective        = NULL,
                cluster_id         = NULL,
                intraday_probability = 0,
                trade_quality      = NULL
            WHERE id IN ({placeholders})
        """, news_ids)

        # Step 3: Delete from alerts table (so Telegram sends them again)
        cursor.execute(f"DELETE FROM alerts WHERE news_id IN ({placeholders})", news_ids)
        deleted_alerts = cursor.rowcount

        # Step 4: Clear dispatch log (keeps analytics clean)
        cursor.execute(f"DELETE FROM alert_dispatch_log WHERE news_id IN ({placeholders})", news_ids)
        deleted_logs = cursor.rowcount

        conn.commit()

        logger.info("\n--- RESET COMPLETE ---")
        logger.info(f"[OK] {len(news_ids)} news items pushed back to Pending (status=0).")
        logger.info(f"[OK] {deleted_alerts} alert record(s) cleared from history.")
        logger.info(f"[OK] {deleted_logs} dispatch log(s) cleared.")
        logger.info("Bot will re-analyze and re-send on its next 3-minute cycle.")

    except sqlite3.OperationalError as e:
        logger.error(f"[DB ERROR] {e}")
        if conn:
            conn.rollback()
        sys.exit(1)
    except Exception as e:
        logger.error(f"[UNEXPECTED ERROR] {e}")
        if conn:
            conn.rollback()
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    reset_news_after_9am()
