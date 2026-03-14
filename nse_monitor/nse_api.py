import requests
import logging
import time
from datetime import datetime
from nse_monitor.config import NSE_BASE_URL, NSE_API_URL, HEADERS

logger = logging.getLogger(__name__)

class NSEClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._init_session()

    def _init_session(self):
        """Initializes session by visiting the home page and announcements page to set cookies."""
        try:
            logger.info("Initializing NSE session (warming up cookies)...")
            
            # 1. Visit Home Page
            self.session.get(NSE_BASE_URL, timeout=15)
            time.sleep(1)
            
            # 2. Visit Announcements Page
            filings_url = f"{NSE_BASE_URL}/companies-listing/corporate-filings-announcements"
            self.session.headers.update({"Referer": NSE_BASE_URL})
            self.session.get(filings_url, timeout=15)
            
            # API specific headers
            self.session.headers.update({
                "Accept": "*/*",
                "Referer": filings_url,
                "X-Requested-With": "XMLHttpRequest",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            })
            
            logger.info("Session stabilized.")
        except Exception as e:
            logger.error(f"Failed to initialize NSE session: {e}")

    def get_announcements(self, from_date=None, to_date=None, retry=1):
        """Fetches announcements from NSE API."""
        if not from_date or not to_date:
            today = datetime.now().strftime("%d-%m-%Y")
            from_date = to_date = today

        params = {
            "index": "equities",
            "from_date": from_date,
            "to_date": to_date,
            "reqXbrl": "false"
        }

        try:
            logger.info(f"Fetching announcements for {from_date} to {to_date}...")
            response = self.session.get(NSE_API_URL, params=params, timeout=20)
            
            if response.status_code in [401, 403]:
                if retry > 0:
                    logger.warning("Access denied. Re-initializing session and retrying...")
                    self._init_session()
                    return self.get_announcements(from_date, to_date, retry=retry-1)
                else:
                    logger.error("Access denied multiple times. NSE might be blocking this IP.")
                    return []

            response.raise_for_status()
            data = response.json()
            
            # Handle possible data structures
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            elif isinstance(data, list):
                return data
            else:
                logger.warning(f"Unexpected API response format: {type(data)}")
                return []

        except Exception as e:
            logger.error(f"Error fetching announcements: {e}")
            return []

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = NSEClient()
    res = client.get_announcements()
    print(f"Items: {len(res)}")
