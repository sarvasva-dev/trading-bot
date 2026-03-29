"""
nse_monitor/sources/global_source.py
v1.0 — Real-Time Global Market Intelligence
Fetches: GIFT Nifty, Dow Jones, Nasdaq, Crude Oil levels
"""
import logging
import requests
import re
import random
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)


class GlobalSource:
    """
    v1.0: Real-time scraper for global market levels used in the Morning Report.
    Fetches GIFT Nifty, Dow Jones, Nasdaq, and Crude Oil from Google Finance.
    """
    NAME = "Global Markets"

    # Google Finance endpoints (lightweight, no JS required for basic data)
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _scrape_price(self, url, label):
        """Scrapes the current price and change% from a Google Finance page."""
        try:
            r = requests.get(url, headers=self._get_headers(), timeout=10)
            r.raise_for_status()
            text = r.text

            # Google Finance price pattern: data-last-price or large numeric in JSON
            # Pattern 1: JSON-like value embedded in page
            price_match = re.search(
                r'"(?:price|lastPrice|regularMarketPrice)"\s*:\s*"?([\d,]+\.?\d*)"?',
                text
            )
            change_match = re.search(
                r'"(?:changePercent|regularMarketChangePercent)"\s*:\s*"?(-?[\d.]+)"?',
                text
            )

            # Pattern 2: Direct data-last-price attribute
            if not price_match:
                price_match = re.search(r'data-last-price="([\d,.]+)"', text)
            if not change_match:
                change_match = re.search(r'data-last-price-change-percent="(-?[\d.]+)"', text)

            # Pattern 3: Look for the large price display pattern
            if not price_match:
                price_match = re.search(r'<span[^>]*jsname="ip75Cb"[^>]*>([\d,]+\.?\d*)<', text)

            if price_match:
                price = price_match.group(1).replace(",", "")
                change = float(change_match.group(1)) if change_match else 0.0
                direction = "▲" if change >= 0 else "▼"
                sign = "+" if change >= 0 else ""
                return f"{float(price):,.0f} ({direction}{sign}{change:.2f}%)"

        except Exception as e:
            logger.warning(f"GlobalSource: Failed to fetch {label}: {e}")
        return None

    def fetch_indices(self):
        """
        Fetches all global market levels.
        Returns a dict with labels as keys and formatted strings as values.
        """
        logger.info("GlobalSource: Fetching live global market levels...")
        results = {}

        for label, url in self.ENDPOINTS.items():
            value = self._scrape_price(url, label)
            if value:
                results[label] = value
                logger.info(f"GlobalSource: {label} = {value}")
            else:
                results[label] = "Data Unavailable"

        return results

    def fetch(self):
        """
        Returns market indices as news items for the main cycle.
        Only used if global news needs to be AI-analyzed.
        """
        # Global indices are not run through AI — only used in morning report
        return []
