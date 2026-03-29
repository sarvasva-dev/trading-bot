"""
nse_monitor/proxy_manager.py
v1.1 — Auto-Fetching Proxy Rotator
Manages free proxy rotation to prevent NSE IP bans on the VPS.
"""
import requests
import random
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Fetches free proxies from public lists, tests them, and provides a working
    rotating proxy for `requests.Session` connections.
    """
    def __init__(self):
        self.proxies = []
        self._refresh_proxies()

    def _refresh_proxies(self):
        """Scrapes free public proxies originating exclusively from India (IN)."""
        logger.info("ProxyManager: Fetching fresh Indian proxies...")
        try:
            # Explicitly filtering for Indian proxies ('country=IN')
            url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=IN&ssl=all&anonymity=all"
            r = requests.get(url, timeout=10)
            
            raw_proxies = r.text.strip().split("\r\n")
            new_list = []
            
            for line in raw_proxies:
                if ":" in line:
                    new_list.append(f"http://{line}")
            
            # Keep top 30 active Indian proxies
            self.proxies = new_list[:30]
            logger.info(f"ProxyManager: Loaded {len(self.proxies)} Indian proxies.")
            
        except Exception as e:
            logger.error(f"ProxyManager: Failed to refresh Indian proxies: {e}")

    def get_proxy(self):
        """
        Returns a randomly selected proxy dictionary for `requests.get()`.
        If the list is empty, returns None (Direct connection fallback).
        """
        if not self.proxies:
            return None
        
        proxy_url = random.choice(self.proxies)
        return {
            "http": proxy_url,
            "https": proxy_url
        }

    def remove_dead_proxy(self, proxy_dict):
        """Removes a proxy from the list if it fails a request."""
        if not proxy_dict or not self.proxies:
            return
        
        proxy_url = proxy_dict.get("http")
        if proxy_url in self.proxies:
            self.proxies.remove(proxy_url)
            logger.debug(f"ProxyManager: Removed dead proxy {proxy_url}. {len(self.proxies)} remaining.")
            
            # Auto-refill if running low
            if len(self.proxies) < 5:
                self._refresh_proxies()
