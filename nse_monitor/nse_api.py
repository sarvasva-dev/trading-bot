import aiohttp
import asyncio
import logging
import random
import pytz
from datetime import datetime, timedelta
from nse_monitor.config import HEADERS, NSE_BASE_URL, NSE_API_URL, USER_AGENTS
# from nse_monitor.proxy_manager import ProxyManager # Keeping imports for potential future use

logger = logging.getLogger(__name__)

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            x = 0
            while x < retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if x == retries - 1:
                        raise e
                    sleep = (backoff_in_seconds * 2 ** x + random.uniform(0.5, 1.5))
                    logger.warning(f"Retrying in {sleep:.2f} seconds after error: {e}")
                    await asyncio.sleep(sleep)
                    x += 1
        return wrapper
    return decorator

class NSEClient:
    def __init__(self, on_403=None):
        self.session = None  # Created lazily in async context
        # self.proxy_mgr = ProxyManager() # Bypassed
        self.current_proxy = None # Direct Mode (per user request)
        self.on_403 = on_403
        self.is_connected = False
        self.lock = asyncio.Lock()

    async def ensure_session(self):
        """Ensures an aiohttp session is active and warmed up."""
        if self.session is None or self.session.closed:
            async with self.lock:
                if self.session is None or self.session.closed:
                    self.session = aiohttp.ClientSession(headers=HEADERS)
                    try:
                        await self._init_session()
                    except Exception as e:
                        logger.error(f"⚠️ Initial NSE Connection Failed: {e}")

    @retry_with_backoff(retries=3, backoff_in_seconds=2)
    async def _init_session(self):
        """Warms up the session with fresh cookies and identity rotation."""
        ua = random.choice(USER_AGENTS)
        logger.info("📡 Connecting to NSE Server (Direct Async Mode)...")
        
        # Reset headers with new UA
        headers = HEADERS.copy()
        headers["User-Agent"] = ua
        self.session._default_headers.update(headers)
        
        try:
            # 1. Visit Home Page (Baseline cookies)
            async with self.session.get(NSE_BASE_URL, timeout=30) as resp:
                await resp.text()
            await asyncio.sleep(random.uniform(1, 3))
            
            # 2. Visit Corporate Filings Page
            url = f"{NSE_BASE_URL}/companies-listing/corporate-filings-announcements"
            async with self.session.get(url, timeout=30) as resp:
                await resp.text()
            
            logger.info("✅ NSE Connection: Secured & Stable (Async).")
            self.is_connected = True
        except Exception as e:
            self.is_connected = False
            logger.warning(f"❌ NSE Connection Failed. Error: {e}")
            raise

    @retry_with_backoff(retries=3, backoff_in_seconds=4)
    async def get_announcements(self, index="equities"):
        """Fetches latest announcements with identity rotation on 403."""
        await self.ensure_session()
        
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        from_date = (now_ist - timedelta(days=1)).strftime("%d-%m-%Y")
        
        params = {
            "index": index,
            "from_date": from_date,
            "to_date": now_ist.strftime("%d-%m-%Y")
        }
        
        logger.info(f"Fetching {index} announcements from {from_date}...")
        
        async with self.session.get(NSE_API_URL, params=params, timeout=15) as response:
            if response.status in [401, 403]:
                logger.warning(f"⚠️ NSE Access Denied (403). Identity Pressure Detected.")
                if self.on_403:
                    try: 
                        msg = f"🚨 <b>NSE IP PRESSURE:</b> 403 on {index}."
                        if asyncio.iscoroutinefunction(self.on_403):
                            await self.on_403(msg)
                        else:
                            self.on_403(msg)
                    except: pass
                
                await self._init_session()
                # Retry once after re-init
                async with self.session.get(NSE_API_URL, params=params, timeout=15) as retry_resp:
                    retry_resp.raise_for_status()
                    data = await retry_resp.json()
            else:
                response.raise_for_status()
                data = await response.json()
            
            return data if isinstance(data, list) else data.get('data', [])

    async def get_json(self, url, params=None, referer=None, warmup=None):
        """Generic robust async JSON fetcher."""
        await self.ensure_session()
        
        current_headers = {}
        if referer:
            current_headers["Referer"] = referer
            
        try:
            if warmup:
                async with self.session.get(warmup, headers=current_headers, timeout=10) as warm_resp:
                    await warm_resp.text()
                
            async with self.session.get(url, params=params, headers=current_headers, timeout=15) as response:
                if response.status in [401, 403]:
                    logger.warning(f"Access denied (403) for {url}. Rotating identity...")
                    await self._init_session()
                    # Retry with new identity
                    if warmup:
                        async with self.session.get(warmup, headers=current_headers, timeout=10) as warm_retry:
                            await warm_retry.text()
                    async with self.session.get(url, params=params, headers=current_headers, timeout=15) as retry_resp:
                        if retry_resp.status != 200: return None
                        return await retry_resp.json()
                        
                if response.status != 200:
                    logger.error(f"NSE API Error {response.status} for {url}")
                    return None
                    
                text = await response.text()
                if not text.strip():
                    return None
                    
                return await response.json()
        except Exception as e:
            logger.error(f"NSE API Request Failed ({url}): {e}")
            return None

    @retry_with_backoff(retries=2, backoff_in_seconds=5)
    async def get_historical_data(self, symbol, days=12):
        """v4.0: Fetches historical Price-Volume-Delivery data (Security-wise)."""
        await self.ensure_session()
        
        ist = pytz.timezone("Asia/Kolkata")
        to_date = datetime.now(ist).strftime("%d-%m-%Y")
        from_date = (datetime.now(ist) - timedelta(days=days)).strftime("%d-%m-%Y")
        
        # v3.0 Discovered endpoint for historical delivery position
        url = "https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData"
        params = {
            "from": from_date,
            "to": to_date,
            "symbol": symbol.upper(),
            "type": "priceVolumeDeliverable",
            "series": "ALL"
        }
        
        # This endpoint requires a valid referer from the report page
        referer = f"https://www.nseindia.com/report-detail/eq_security?symbol={symbol.upper()}"
        
        logger.info(f"📊 Fetching Smart Money Data for {symbol} ({from_date} to {to_date})")
        
        data = await self.get_json(url, params=params, referer=referer)
        if not data or not isinstance(data, dict) or 'data' not in data:
            return []
            
        return data['data']

    async def close(self):
        """Closes the underlying aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
