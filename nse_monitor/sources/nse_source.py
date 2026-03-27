import logging
import time
from nse_monitor.nse_api import NSEClient

logger = logging.getLogger(__name__)

class NSESource:
    NAME = "NSE"

    def __init__(self, client=None):
        self.client = client or NSEClient()

    def fetch(self):
        """Fetches latest corporate announcements from NSE."""
        logger.info("Fetching data from NSE Source...")
        try:
            announcements = self.client.get_announcements()
            logger.info(f"NSE API returned {len(announcements)} raw items.")
            results = []
            for ann in announcements:
                # Use Subject as Headline for better uniqueness and context
                headline = ann.get('subject', '') or ann.get('desc', '')
                
                # Use Description as category/type info
                category = ann.get('desc', '')

                results.append({
                    "source": "NSE",
                    "headline": headline,
                    "symbol": ann.get('symbol', 'N/A'),
                    "summary": f"Category: {category}. {headline}", # Combine for full context
                    "url": f"https://nsearchives.nseindia.com/corporate/{ann.get('attchmntFile')}" if ann.get('attchmntFile') and 'http' not in ann.get('attchmntFile') else ann.get('attchmntFile', ''),
                    "timestamp": ann.get('dt', '') or time.strftime("%d-%b-%Y %H:%M:%S"),
                    "raw_id": str(ann.get('sm_pid') or ann.get('id'))
                })
            return results
        except Exception as e:
            logger.error(f"NSE Source fetch failed: {e}")
            return []
