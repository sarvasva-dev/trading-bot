import logging
import aiohttp
import asyncio
import re
import random
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)

class GlobalSource:
    NAME = "Global Markets"
    ENDPOINTS = {
        "GIFT Nifty":  "https://www.google.com/finance/quote/NIFTY_FUT:NSE",
        "Dow Jones":   "https://www.google.com/finance/quote/.DJI:INDEXDJX",
        "Nasdaq":      "https://www.google.com/finance/quote/.IXIC:INDEXNASDAQ",
        "Crude Oil":   "https://www.google.com/finance/quote/USOIL:FX_IDC",
    }

    def _get_headers(self):
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def _scrape_price(self, session, url, label):
        try:
            async with session.get(url, headers=self._get_headers(), timeout=10) as resp:
                text = await resp.text()
                
                # Try multiple patterns for price/change
                price_match = re.search(r'"(?:price|lastPrice|regularMarketPrice)"\s*:\s*"?([\d,]+\.?\d*)"?', text)
                if not price_match: price_match = re.search(r'data-last-price="([\d,.]+)"', text)
                if not price_match: price_match = re.search(r'<span[^>]*jsname="ip75Cb"[^>]*>([\d,]+\.?\d*)<', text)
                
                change_match = re.search(r'"(?:changePercent|regularMarketChangePercent)"\s*:\s*"?(-?[\d.]+)"?', text)
                if not change_match: change_match = re.search(r'data-last-price-change-percent="(-?[\d.]+)"', text)
                
                if price_match:
                    p = float(price_match.group(1).replace(",", ""))
                    c = float(change_match.group(1)) if change_match else 0.0
                    icon = "▲" if c >= 0 else "▼"
                    return f"{p:,.0f} ({icon}{'+' if c>=0 else ''}{c:.2f}%)"
        except Exception as e:
            logger.warning(f"GlobalSource: {label} fetch failed: {e}")
        return "Data Unavailable"

    async def fetch_indices(self):
        """Fetches all indices concurrently (Async)."""
        async with aiohttp.ClientSession() as session:
            tasks = [self._scrape_price(session, url, label) for label, url in self.ENDPOINTS.items()]
            results = await asyncio.gather(*tasks)
            return dict(zip(self.ENDPOINTS.keys(), results))

    def fetch(self): return []
