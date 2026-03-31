import logging
import asyncio
import time
from nse_monitor.nse_api import NSEClient

logger = logging.getLogger(__name__)

class NseSmeSource:
    NAME = "NSE_SME"

    def __init__(self, client=None):
        self.client = client or NSEClient()

    async def fetch(self):
        """Fetches latest corporate announcements from the NSE SME segment (Async)."""
        logger.info("Fetching data from NSE SME Source...")
        try:
            announcements = await self.client.get_announcements(index="sme")
            logger.info(f"NSE SME API returned {len(announcements)} raw items.")
            results = []
            for ann in announcements:
                headline = ann.get("subject", "") or ann.get("desc", "")
                category = ann.get("desc", "")
                attach = ann.get("attchmntFile", "")
                url = f"https://nsearchives.nseindia.com/corporate/{attach}" if attach and "http" not in attach else attach
                
                results.append({
                    "source": "NSE_SME",
                    "headline": headline,
                    "symbol": ann.get("symbol", "N/A"),
                    "summary": f"[SME] Category: {category}. {headline}",
                    "url": url,
                    "timestamp": ann.get("dt", "") or time.strftime("%d-%b-%Y %H:%M:%S"),
                    "raw_id": str(ann.get("sm_pid") or ann.get("id", "")),
                    "is_sme": True
                })
            return results
        except Exception as e:
            logger.error(f"NSE SME Source fetch failed: {e}")
            return []
