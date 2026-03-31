import logging
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import time
import random
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)

class MoneycontrolSource:
    NAME = "MoneyControl"

    def __init__(self):
        self.url = "https://www.moneycontrol.com/news/business/markets/"

    def _get_headers(self):
        return {"User-Agent": random.choice(USER_AGENTS)}

    async def fetch(self):
        """Scrapes latest market news from Moneycontrol (Async)."""
        logger.info("Fetching data from Moneycontrol Source...")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.url, headers=self._get_headers(), timeout=15) as resp:
                    if resp.status != 200: return []
                    html = await resp.text()
                
                soup = BeautifulSoup(html, 'lxml')
                news_list = soup.select('#cagetory li.clearfix') or soup.select('li.clearfix') or soup.select('.latest_news li')
                
                results = []
                tasks = []
                seen_links = set()

                for item in news_list[:5]:
                    title_tag = item.find('h2') or item.find('a')
                    if not title_tag: continue
                    
                    link_tag = title_tag.find('a') if title_tag.name != 'a' else title_tag
                    if not link_tag: continue
                    
                    link = link_tag.get('href', "")
                    if not link: continue
                    if not link.startswith('http'): link = "https://www.moneycontrol.com" + link
                    
                    if link in seen_links: continue
                    seen_links.add(link)
                    
                    headline = link_tag.text.strip()
                    tasks.append(self._fetch_full_article(session, link, headline))

                article_results = await asyncio.gather(*tasks)
                for res in article_results:
                    if res: results.append(res)
                
                return results
            except Exception as e:
                logger.error(f"Moneycontrol fetch failed: {e}")
                return []

    async def _fetch_full_article(self, session, url, headline):
        try:
            async with session.get(url, headers=self._get_headers(), timeout=10) as resp:
                if resp.status != 200: return None
                text = await resp.text()
            
            s = BeautifulSoup(text, 'lxml')
            content = s.select_one('#contentdata') or s.select_one('.content_wrapper') or s.select_one('.article_fullbody')
            full_text = content.text.strip()[:6000] if content else headline
            
            return {
                "source": "Moneycontrol",
                "headline": headline,
                "summary": full_text,
                "url": url,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        except: return None
