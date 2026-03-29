import logging
import time
from nse_monitor.nse_api import NSEClient

logger = logging.getLogger(__name__)


class NseSmeSource:
    """
    v1.0: Fetches NSE SME Segment Corporate Announcements.
    SME stocks have extreme volatility — highest profit potential for traders.
    """
    NAME = "NSE_SME"

    def __init__(self, client=None):
        self.client = client or NSEClient()

    def fetch(self):
        """Fetches latest corporate announcements from the NSE SME segment."""
        logger.info("Fetching data from NSE SME Source...")
        try:
            import pytz
            from datetime import datetime, timedelta
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
            from_date = (now_ist - timedelta(days=1)).strftime("%d-%m-%Y")
            to_date = now_ist.strftime("%d-%m-%Y")

            params = {
                "index": "sme",           # <— SME segment key
                "from_date": from_date,
                "to_date": to_date
            }

            from nse_monitor.config import NSE_API_URL
            response = self.client.session.get(NSE_API_URL, params=params, timeout=15)

            if response.status_code in [401, 403]:
                logger.warning("SME: Access denied (403). Rotating identity...")
                self.client._init_session()
                response = self.client.session.get(NSE_API_URL, params=params, timeout=15)

            response.raise_for_status()
            data = response.json()
            announcements = data if isinstance(data, list) else data.get("data", [])

            logger.info(f"NSE SME API returned {len(announcements)} raw items.")
            results = []
            for ann in announcements:
                headline = ann.get("subject", "") or ann.get("desc", "")
                category = ann.get("desc", "")
                attach = ann.get("attchmntFile", "")
                url = (
                    f"https://nsearchives.nseindia.com/corporate/{attach}"
                    if attach and "http" not in attach
                    else attach
                )
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
