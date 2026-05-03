import sys
import os
import logging

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.database import Database
from nse_monitor.sync_bridge import SupabaseSyncBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ForceSync")

def main():
    logger.info("Starting Force Sync of User Data to Supabase...")
    
    db = Database()
    
    # 1. Backfill the outbox with all existing users
    logger.info("Seeding outbox with existing users (Backfill)...")
    count = db.backfill_supabase_outbox()
    logger.info(f"Queued {count} users for sync.")
    
    # 2. Flush the outbox
    bridge = SupabaseSyncBridge(db)
    if not bridge.client.is_ready():
        logger.error("Supabase credentials missing in .env! Cannot sync.")
        return

    logger.info("Flushing outbox to Supabase...")
    total_synced = 0
    while True:
        stats = bridge.flush_once()
        if stats.get("skipped"):
            logger.error("Sync skipped (Client not ready).")
            break
            
        synced = stats.get("synced", 0)
        total_synced += synced
        
        if stats.get("queued", 0) == 0:
            logger.info("Outbox is empty. Sync complete.")
            break
            
        logger.info(f"Batch synced: {synced}. Total so far: {total_synced}")
        
    logger.info(f"Done! Successfully pushed {total_synced} records to Supabase.")

if __name__ == "__main__":
    main()
