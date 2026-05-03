import logging
import requests
from typing import Dict, Any, List
from nse_monitor.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

logger = logging.getLogger("SupabaseSync")

class SupabaseClient:
    """Sidecar HTTP client for asynchronous Supabase mirroring (REST API, no SDK dependency)."""

    def __init__(self):
        self.url = SUPABASE_URL.rstrip("/") if SUPABASE_URL else ""
        self.key = SUPABASE_SERVICE_ROLE_KEY
        self._ready = bool(self.url and self.key)
        if self._ready:
            logger.info("Supabase Client Initialized (REST mode).")
        else:
            logger.warning("Supabase credentials missing. Sync will be disabled.")

    def is_ready(self) -> bool:
        return self._ready

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

    def _post(self, table: str, rows: List[Dict[str, Any]]) -> bool:
        """Upsert rows into a Supabase table via REST. Returns True on success."""
        if not self._ready or not rows:
            return False
        endpoint = f"{self.url}/rest/v1/{table}"
        try:
            resp = requests.post(
                endpoint,
                json=rows,
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code in (200, 201):
                return True
            logger.error("Supabase POST %s → %s: %s", table, resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("Supabase POST %s exception: %s", table, e)
            return False

    def upsert_user(self, user_data: Dict[str, Any]) -> bool:
        return self._post("users", [user_data])

    def log_referral_event(self, event_data: Dict[str, Any]) -> bool:
        return self._post("referral_events", [event_data])

    def push_signal(self, signal_data: Dict[str, Any]) -> bool:
        return self._post("signals", [signal_data])

    def sync_batch(self, entity_type: str, rows: List[Dict[str, Any]]) -> bool:
        return self._post(entity_type, rows)

    def upsert_daily_stats(self, payload: Dict[str, Any]) -> bool:
        return self._post("dispatch_stats_daily", [payload])
