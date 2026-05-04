import time
import json
import logging
import signal
import sys
from datetime import datetime
from nse_monitor.database import Database
from nse_monitor.supabase_client import SupabaseClient
from nse_monitor.config import ENABLE_SUPABASE_SYNC

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("SyncWorker")

class SyncWorker:
    def __init__(self):
        self.db = Database()
        self.sb = SupabaseClient()
        self.running = True
        
        # Graceful shutdown
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def stop(self, *args):
        logger.info("SyncWorker stopping...")
        self.running = False

    def process_outbox(self):
        if not ENABLE_SUPABASE_SYNC:
            return
        
        if not self.sb.is_ready():
            logger.warning("Supabase Client not ready. Skipping cycle.")
            return

        rows = self.db.get_pending_sync_rows(limit=50)
        if not rows:
            return

        logger.info(f"Processing {len(rows)} outbox items...")
        
        for row in rows:
            row_id = row["id"]
            entity_type = row["entity_type"]
            payload = json.loads(row["payload_json"])
            
            success = False
            try:
                # Direct table mapping
                # Supabase tables should match SQLite entity_type (users, referral_events, etc.)
                success = self.sb.sync_batch(entity_type, [payload])
            except Exception as e:
                logger.error(f"Sync error for row {row_id}: {e}")
            
            if success:
                self.db.mark_sync_row_done(row_id)
                logger.info(f"Synced {entity_type} ID {row['entity_id']}")
            else:
                self.db.mark_sync_row_failed(row_id, "Supabase API Error or Connection Issue")

    def sync_aggregates(self):
        """Sync daily business metrics to Supabase for dashboarding."""
        try:
            total, active = self.db.get_user_stats()
            date_str = datetime.now().strftime("%Y-%m-%d")
            payload = {
                "metric_date": date_str,
                "active_users": active,
                "total_users": total,
            }
            self.sb.upsert_daily_stats(payload)
            logger.info(f"Daily metrics synced for {date_str}")
        except Exception as e:
            logger.error(f"Aggregates sync failed: {e}")

    def startup_backfill(self):
        """On restart: replay any pending outbox rows, then backfill recent users not yet in outbox."""
        if not ENABLE_SUPABASE_SYNC or not self.sb.is_ready():
            return
        # 1. Replay existing pending/failed rows first
        self.process_outbox()
        # 2. Backfill all users into outbox (INSERT OR IGNORE semantics via add_sync_outbox_row)
        count = self.db.backfill_supabase_outbox()
        logger.info(f"Startup backfill: queued {count} user rows for Supabase mirror.")
        # 3. Process the newly queued rows
        self.process_outbox()

    def process_inbox(self):
        """v8.2: Polls and executes commands from Supabase SmartAdmin."""
        if not ENABLE_SUPABASE_SYNC or not self.sb.is_ready():
            return
            
        commands = self.sb.get_pending_commands()
        if not commands:
            return
            
        logger.info(f"Received {len(commands)} commands from SmartAdmin.")
        for cmd in commands:
            cmd_id = cmd.get("id")
            ctype = cmd.get("command_type")
            payload = cmd.get("payload", {})
            
            try:
                if ctype == "grant_days":
                    target = payload.get("chat_id")
                    days = payload.get("days", 0)
                    if target and days:
                        self.db.add_working_days(target, days)
                        self.db.toggle_user_status(target, 1)
                        self.db.record_billing_event(target, "CREDIT", days, "SmartAdmin Manual Grant")
                
                elif ctype == "toggle_free_trial":
                    enabled = payload.get("enabled", False)
                    self.db.set_free_trial_enabled(enabled, admin_chat_id="SmartAdmin")
                
                elif ctype == "block_user":
                    target = payload.get("chat_id")
                    if target:
                        self.db.toggle_user_status(target, 0)
                
                elif ctype == "unblock_user":
                    target = payload.get("chat_id")
                    if target:
                        self.db.toggle_user_status(target, 1)
                        
                # Mark as completed
                self.sb.mark_command_done(cmd_id, "completed")
                logger.info(f"Executed SmartAdmin command {ctype} for {cmd_id}")
            except Exception as e:
                logger.error(f"Failed to execute command {cmd_id}: {e}")
                self.sb.mark_command_done(cmd_id, "failed")

    def run(self):
        logger.info("=== Bulkbeat TV Sync Worker Started ===")
        if not ENABLE_SUPABASE_SYNC:
            logger.warning("ENABLE_SUPABASE_SYNC is OFF. Worker will idle.")

        self.startup_backfill()

        while self.running:
            try:
                self.process_outbox()
                if ENABLE_SUPABASE_SYNC:
                    self.sync_aggregates()
                    self.process_inbox()
            except Exception as e:
                logger.error(f"Main loop error: {e}")
            
            # Wait for 30 seconds or until stopped
            for _ in range(30):
                if not self.running: break
                time.sleep(1)

if __name__ == "__main__":
    SyncWorker().run()
