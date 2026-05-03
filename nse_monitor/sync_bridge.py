import json
import logging
from datetime import datetime
from typing import Dict

from nse_monitor.config import SUPABASE_SYNC_BATCH_SIZE
from nse_monitor.supabase_client import SupabaseClient

logger = logging.getLogger("SupabaseSyncBridge")


class SupabaseSyncBridge:
    """Sidecar worker that flushes SQLite outbox rows to Supabase."""

    def __init__(self, db):
        self.db = db
        self.client = SupabaseClient()
        self.batch_size = max(1, int(SUPABASE_SYNC_BATCH_SIZE))

    @staticmethod
    def _target_table(entity_type: str) -> str:
        mapping = {
            "users": "users_public",
            "referral_events": "referral_events",
            "conversion_events": "conversion_events",
            "subscription_events": "subscription_events",
            "signals": "signals",
        }
        return mapping.get(entity_type, entity_type)

    def _normalize_payload(self, entity_type: str, payload: Dict) -> Dict:
        data = dict(payload or {})
        if entity_type == "users":
            # Supabase mirror table key is user_id
            data["user_id"] = str(data.get("user_id") or data.get("id") or "")
            data.pop("id", None)
        return data

    def _sync_daily_dispatch_stats(self) -> None:
        """Exports dispatch_stats_daily aggregate row (IST/localtime from SQLite)."""
        metric_date = datetime.now().strftime("%Y-%m-%d")
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM alert_dispatch_log WHERE date(dispatch_time)=date('now','localtime')")
        signals_sent = int(cursor.fetchone()[0] or 0)
        cursor.execute("SELECT COUNT(*) FROM news_items WHERE processing_status=3")
        signals_queued = int(cursor.fetchone()[0] or 0)
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active=1")
        active_users = int(cursor.fetchone()[0] or 0)

        self.client.sync_batch("dispatch_stats_daily", [{
            "metric_date": metric_date,
            "signals_sent": signals_sent,
            "signals_queued": signals_queued,
            "active_users": active_users,
        }])

    def _sync_referral_metrics_daily(self) -> None:
        """Exports referral_metrics_daily aggregates by referrer for today."""
        metric_date = datetime.now().strftime("%Y-%m-%d")
        cursor = self.db.conn.cursor()
        cursor.execute(
            """SELECT referrer_user_id,
                      COUNT(CASE WHEN event_type='signup' THEN 1 END) AS joins,
                      COUNT(CASE WHEN event_type='converted' THEN 1 END) AS conversions,
                      COALESCE(SUM(CASE WHEN event_type='converted' THEN amount ELSE 0 END), 0) AS paid_amount,
                      COALESCE(SUM(CASE WHEN event_type='reward_credited' THEN amount ELSE 0 END), 0) AS reward_due
               FROM referral_events
               WHERE date(created_at)=date('now','localtime')
               GROUP BY referrer_user_id"""
        )
        rows = cursor.fetchall()
        if not rows:
            return

        payout_map = {}
        cursor.execute(
            """SELECT target_user_id, COALESCE(SUM(amount_rupees), 0)
               FROM referral_admin_actions
               WHERE action_type='payout_marked' AND date(created_at)=date('now','localtime')
               GROUP BY target_user_id"""
        )
        for uid, amt in cursor.fetchall():
            payout_map[str(uid)] = int(amt or 0)

        payloads = []
        for uid, joins, conversions, paid_amount, reward_due in rows:
            payloads.append({
                "metric_date": metric_date,
                "referrer_user_id": str(uid),
                "joins": int(joins or 0),
                "conversions": int(conversions or 0),
                "paid_amount": int(paid_amount or 0),
                "reward_due": int(reward_due or 0),
                "reward_paid": int(payout_map.get(str(uid), 0)),
            })

        self.client.sync_batch("referral_metrics_daily", payloads)

    def _ensure_backfill_once(self) -> None:
        """Queues legacy users once so Supabase always has full user-list backup."""
        done = self.db.get_config("supabase_backfill_done", "0")
        if done == "1":
            return
        try:
            count = self.db.backfill_supabase_outbox()
            self.db.set_config("supabase_backfill_done", "1")
            logger.info("Supabase backfill seeded: %s users queued", count)
        except Exception as e:
            logger.error("Supabase backfill failed: %s", e)

    def flush_once(self) -> Dict[str, int]:
        """Processes one outbox batch and returns counters for observability."""
        if not self.client.is_ready():
            return {"queued": 0, "synced": 0, "failed": 0, "skipped": 1}

        self._ensure_backfill_once()

        rows = self.db.get_pending_sync_rows(limit=self.batch_size, apply_backoff=True)
        if not rows:
            try:
                self._sync_daily_dispatch_stats()
                self._sync_referral_metrics_daily()
            except Exception as e:
                logger.error("Daily metrics sync failed: %s", e)
            return {"queued": 0, "synced": 0, "failed": 0, "skipped": 0}

        synced = 0
        failed = 0
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                entity_type = row["entity_type"]
                target = self._target_table(entity_type)
                normalized = self._normalize_payload(entity_type, payload)
                ok = self.client.sync_batch(target, [normalized])
                if ok:
                    self.db.mark_sync_row_done(row["id"])
                    synced += 1
                else:
                    self.db.mark_sync_row_failed(row["id"], "Supabase API error")
                    failed += 1
            except Exception as e:
                self.db.mark_sync_row_failed(row["id"], str(e))
                failed += 1

        # Best-effort daily aggregate mirrors (independent from outbox rows)
        try:
            self._sync_daily_dispatch_stats()
            self._sync_referral_metrics_daily()
        except Exception as e:
            logger.error("Daily metrics sync failed: %s", e)

        return {"queued": len(rows), "synced": synced, "failed": failed, "skipped": 0}
