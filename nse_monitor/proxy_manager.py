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
        # Proxy layer is intentionally disabled; keep direct mode only.
        logger.info("ProxyManager: Disabled (direct mode forced).")

    def _refresh_proxies(self):
        """Scrapes free public proxies originating exclusively from India (IN)."""
        self.proxies = []
        logger.info("ProxyManager: Refresh skipped (disabled).")

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
