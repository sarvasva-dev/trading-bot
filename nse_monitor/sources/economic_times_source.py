import logging
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import time
import random
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)

class EconomicTimesSource:
    NAME = "EconomicTimes"

    def __init__(self):
        self.url = "https://economictimes.indiatimes.com/markets/stocks/news"

    def _get_headers(self):
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": "https://economictimes.indiatimes.com/",
        }

    async def fetch(self):
        """Scrapes latest market news from Economic Times (Async)."""
        logger.info("Fetching data from Economic Times Source...")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.url, headers=self._get_headers(), timeout=15) as resp:
                    if resp.status != 200: return []
                    html = await resp.text()
                
                soup = BeautifulSoup(html, 'lxml')
                news_items = soup.select('.eachStory') or soup.select('.story-box') or soup.select('.media-body')
                
                if not news_items:
                    # Fallback to Stocks Landing Page
                    async with session.get("https://economictimes.indiatimes.com/markets/stocks", headers=self._get_headers(), timeout=15) as resp:
                        html = await resp.text()
                    soup = BeautifulSoup(html, 'lxml')
                    news_items = soup.select('.eachStory') or soup.select('.story-box')

                results = []
                tasks = []
                seen_links = set()

                for item in news_items:
                    if len(results) >= 7: break
                    
                    link_tag = item.find('a')
                    if not link_tag: continue
                    
                    link = link_tag.get('href', "")
                    if not link: continue
                    if not link.startswith('http'): link = "https://economictimes.indiatimes.com" + link
                    
                    if link in seen_links or "/videoshow/" in link or "/liveblog/" in link: continue
                    seen_links.add(link)
                    
                    headline = link_tag.text.strip()
                    if len(headline) < 10: continue

                    tasks.append(self._fetch_full_article(session, link, headline))

                # Process all article fetches concurrently
                article_results = await asyncio.gather(*tasks)
                for res in article_results:
                    if res: results.append(res)
                
                return results
            except Exception as e:
                logger.error(f"ET Source fetch failed: {e}")
                return []

    async def _fetch_full_article(self, session, url, headline):
        try:
            async with session.get(url, headers=self._get_headers(), timeout=10) as resp:
                if resp.status != 200: return None
                text = await resp.text()
            
            s = BeautifulSoup(text, 'lxml')
            content = s.select_one('.artText') or s.select_one('.story_art') or s.select_one('.articletext')
            full_text = content.text.strip()[:6000] if content else headline
            
            return {
                "source": "Economic Times",
                "headline": headline,
                "summary": full_text,
                "url": url,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        except: return None
