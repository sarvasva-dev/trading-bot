import requests
import time
import logging
import random
from datetime import datetime, timedelta
from nse_monitor.config import HEADERS, NSE_BASE_URL, NSE_API_URL, USER_AGENTS
from nse_monitor.proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            x = 0
            while x < retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries - 1:
                        raise e
                    sleep = (backoff_in_seconds * 2 ** x + random.uniform(0.5, 1.5))
                    logger.warning(f"Retrying in {sleep:.2f} seconds after error: {e}")
                    time.sleep(sleep)
                    x += 1
        return wrapper
    return decorator

class NSEClient:
    def __init__(self, on_403=None):
        self.session = requests.Session()
        self.proxy_mgr = ProxyManager()
        self.current_proxy = None
        self.on_403 = on_403 # Callback for admin alerts (v1.3)
        self._init_session()

    @retry_with_backoff(retries=3, backoff_in_seconds=2)
    def _init_session(self):
        """Warms up the session with a fresh User-Agent and optionally a Proxy."""
        try:
            ua = random.choice(USER_AGENTS)
            logger.info("📡 Connecting to NSE Server...")
            
            # Reset headers with new UA
            current_headers = HEADERS.copy()
            current_headers["User-Agent"] = ua
            self.session.headers.clear()
            self.session.headers.update(current_headers)
            
            # v1.1 - Retrieve a fresh proxy
            self.current_proxy = self.proxy_mgr.get_proxy()
            if self.current_proxy:
                logger.info(f"Using Proxy: {self.current_proxy['http']}")
            
            # 1. Visit Home Page (Crucial for baseline cookies)
            self.session.get(NSE_BASE_URL, proxies=self.current_proxy, timeout=30)
            time.sleep(random.uniform(1, 3))
            
            # 2. Visit Circulars Landing Page (Stabilizes session)
            self.session.get(f"{NSE_BASE_URL}/companies-listing/corporate-filings-announcements", 
                             proxies=self.current_proxy, timeout=30)
            logger.info("✅ NSE Connection: Secured & Stable.")
        except Exception as e:
            logger.warning(f"❌ NSE Connection Failed with proxy {self.current_proxy}. Retrying...")
            if self.current_proxy:
                self.proxy_mgr.remove_dead_proxy(self.current_proxy)
            raise

    @retry_with_backoff(retries=3, backoff_in_seconds=4)
    def get_announcements(self):
        """Fetches latest announcements with identity rotation on 403."""
        try:
            # RULE #3: 1-Day Lookback using IST for precision (v13.0)
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
            from_date = (now_ist - timedelta(days=1)).strftime("%d-%m-%Y")
            params = {
                "index": "equities",
                "from_date": from_date,
                "to_date": time.strftime("%d-%m-%Y")
            }
            logger.info(f"Fetching announcements from {from_date} (Attempting to hit API)...")
            response = self.session.get(NSE_API_URL, params=params, proxies=self.current_proxy, timeout=15)
            
            if response.status_code in [401, 403]:
                logger.warning(f"⚠️ NSE Access Denied (403). Identity Pressure Detected.")
                # Notify Admin if callback provided
                if self.on_403:
                    try:
                        self.on_403(f"🚨 <b>NSE IP PRESSURE:</b> Received 403 on API. Using proxy: {self.current_proxy['http'] if self.current_proxy else 'Direct'}")
                    except: pass
                
                if self.current_proxy:
                     self.proxy_mgr.remove_dead_proxy(self.current_proxy)
                self._init_session() # Rotate UA and proxy
                response = self.session.get(NSE_API_URL, params=params, proxies=self.current_proxy, timeout=15)

            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else data.get('data', [])
        except Exception as e:
            logger.error(f"Error fetching announcements: {e}")
            raise

    def get_json(self, url, params=None, referer=None, warmup=None):
        """Generic robust JSON fetcher for any NSE API endpoint."""
        # ERROR FIX v1.1: self.headers didn't exist, must be self.session.headers
        headers = dict(self.session.headers)
        if referer:
            headers["Referer"] = referer
            
        try:
            # 1. Warm up if needed (Visit the parent page first)
            if warmup:
                self.session.get(warmup, headers=headers, proxies=self.current_proxy, timeout=10)
                
            # 2. Extract JSON
            response = self.session.get(url, params=params, headers=headers, proxies=self.current_proxy, timeout=15)
            
            # 3. Handle 403/401 with identity rotation
            if response.status_code in [401, 403]:
                logger.warning(f"Access denied (403) for {url}. Rotating identity and proxy...")
                if self.current_proxy:
                     self.proxy_mgr.remove_dead_proxy(self.current_proxy)
                self._init_session()
                # Use updated headers
                headers = dict(self.session.headers)
                if referer: headers["Referer"] = referer
                
                if warmup: 
                    self.session.get(warmup, headers=headers, proxies=self.current_proxy, timeout=10)
                response = self.session.get(url, params=params, headers=headers, proxies=self.current_proxy, timeout=15)
                
            if response.status_code != 200:
                logger.error(f"NSE API Error {response.status_code} for {url}")
                return None
                
            if not response.text.strip():
                logger.warning(f"NSE API returned empty response for {url}")
                # Try one more time with a fresh session
                if self.current_proxy:
                     self.proxy_mgr.remove_dead_proxy(self.current_proxy)
                self._init_session()
                headers = dict(self.session.headers)
                if referer: headers["Referer"] = referer
                response = self.session.get(url, params=params, headers=headers, proxies=self.current_proxy, timeout=15)
                if not response.text.strip(): return None
                
            return response.json()
        except Exception as e:
            logger.error(f"NSE API Request Failed ({url}): {e}")
            return None
