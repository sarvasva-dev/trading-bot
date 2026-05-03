import logging
import aiohttp
import asyncio
import time
import random
from bs4 import BeautifulSoup
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)

class MoneycontrolSource:
    NAME = "MoneyControl"

    def __init__(self):
        self.url = "https://www.moneycontrol.com/news/business/markets/"
        self._session = None

    def _get_headers(self):
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.moneycontrol.com/",
        }

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def fetch(self):
        """Scrapes latest market news from Moneycontrol (Async)."""
        logger.info("Fetching data from Moneycontrol Source...")
        session = await self._get_session()
        try:
            async with session.get(self.url, headers=self._get_headers(), timeout=15) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

            soup = BeautifulSoup(html, 'lxml')
            news_list = (soup.select('#cagetory li.clearfix') or
                         soup.select('li.clearfix') or
                         soup.select('.latest_news li'))

            results = []
            seen_links = set()

            for item in news_list[:5]:
                title_tag = item.find('h2') or item.find('a')
                if not title_tag:
                    continue
                link_tag = title_tag.find('a') if title_tag.name != 'a' else title_tag
                if not link_tag:
                    continue
                link = link_tag.get('href', '')
                if not link:
                    continue
                if not link.startswith('http'):
                    link = "https://www.moneycontrol.com" + link
                if link in seen_links:
                    continue
                seen_links.add(link)
                headline = link_tag.text.strip()
                if len(headline) < 10:
                    continue

                # Stagger article fetches — no parallel burst to MC
                await asyncio.sleep(random.uniform(0.5, 1.2))
                res = await self._fetch_full_article(session, link, headline)
                if res:
                    results.append(res)

            return results
        except Exception as e:
            logger.error("Moneycontrol fetch failed: %s", e)
            return []

    async def _fetch_full_article(self, session, url, headline):
        try:
            async with session.get(url, headers=self._get_headers(), timeout=10) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
            s = BeautifulSoup(text, 'lxml')
            content = (s.select_one('#contentdata') or
                       s.select_one('.content_wrapper') or
                       s.select_one('.article_fullbody'))
            full_text = content.text.strip()[:6000] if content else headline
            return {
                "source": "Moneycontrol",
                "headline": headline,
                "summary": full_text,
                "url": url,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "raw_id": url,
            }
        except Exception as e:
            logger.debug("MC article fetch failed (%s): %s", url, e)
            return None
