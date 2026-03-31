import asyncio
import logging
import time
import inspect
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class NudgeManager:
    """v4.3: Automated Retention System for Trial Conversion."""
    
    def __init__(self, db, bot):
        self.db = db
        self.bot = bot
        self.last_run = 0

    async def run_audit(self):
        """Scans the database for retention opportunities."""
        now = time.time()
        # Run once every 4 hours to avoid spamming
        if now - self.last_run < (4 * 3600):
            return
        
        self.last_run = now
        logger.info("📡 NudgeManager: Running retention audit...")
        
        try:
            # 1. Expiry Nudge (< 24h left)
            await self._nudge_expiring_users()
            
            # 2. Inactivity Nudge (Inactive for 1 trading day)
            await self._nudge_inactive_users()
            
        except Exception as e:
            logger.error(f"NudgeManager Error: {e}")

    async def _nudge_expiring_users(self):
        """Sends a nudge to users with exactly 1 market-day left."""
        users = self.db.get_users_by_remaining_days(1)
        for user_id in users:
            msg = (
                "⏳ <b>Final Trial Day!</b>\n"
                "Your 2-day Institutional Trial expires in 1 market-day.\n\n"
                "To continue receiving high-conviction signals without interruption, choose a plan below.\n\n"
                "👉 /subscribe"
            )
            result = self.bot._send_raw(user_id, msg)
            if inspect.isawaitable(result):
                await result
            logger.info(f"Nudge Sent (Expiry): {user_id}")
            await asyncio.sleep(0.5)

    async def _nudge_inactive_users(self):
        """Placeholder for inactivity nudges. Requires activity tracking in DB."""
        # This will be expanded once last_active_at is tracked in database.py
        pass
