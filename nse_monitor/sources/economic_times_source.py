import logging
import requests
from bs4 import BeautifulSoup
import time
import random
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)

class EconomicTimesSource:
    NAME = "EconomicTimes"

    def __init__(self):
        self.url = "https://economictimes.indiatimes.com/markets"

    def fetch(self):
        """Scrapes latest market news and deep context from Economic Times."""
        logger.info("Fetching data from Economic Times Source...")
        try:
            # Shift to the specialized news feed for better reliability
            news_url = "https://economictimes.indiatimes.com/markets/stocks/news"
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            response = requests.get(news_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            # Updated to focus on .eachStory which is standard for feeds
            # Fallback selectors for resilience
            news_items = soup.select('.eachStory') or \
                         soup.select('.top-news li') or \
                         soup.select('div.media-body') or \
                         soup.select('.story-box') or \
                         soup.select('div.story-box') or \
                         soup.select('div.story_list li')
            
            # If still nothing, try scraping the main markets page as fallback
            if not news_items:
                logger.warning("ET News URL empty, trying main Markets page fallback...")
                response = requests.get("https://economictimes.indiatimes.com/markets", headers=headers, timeout=15)
                soup = BeautifulSoup(response.text, 'lxml')
                news_items = soup.select('.eachStory') or soup.select('.top-news li')

            results = []
            for item in news_items[:5]:
                title_tag = item.find('h3') or item.find('a')
                if not title_tag: continue
                
                headline = title_tag.text.strip()
                link = title_tag['href'] if title_tag.has_attr('href') else (title_tag.find('a')['href'] if title_tag.find('a') else "")
                
                if not link.startswith('http'):
                    link = "https://economictimes.indiatimes.com" + link
                
                # Skip multimedia pages (videos/slideshows) that don't have text content
                if any(x in link for x in ["/videoshow/", "/slideshow/", "/liveblog/"]):
                    logger.debug(f"Skipping multimedia/live story: {headline}")
                    continue

                # Fetch deeper context for AI
                full_text = self._fetch_full_article(link, headers)

                results.append({
                    "source": "Economic Times",
                    "headline": headline,
                    "summary": full_text or headline,
                    "url": link,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })
            
            logger.info(f"Fetched {len(results)} items from Economic Times (Latest and Deep).")
            return results
        except Exception as e:
            logger.error(f"Economic Times Source fetch failed: {e}")
            return []

    def _fetch_full_article(self, url, headers):
        """Fetches the actual article body for better AI analysis."""
        try:
            r = requests.get(url, headers=headers, timeout=10)
            s = BeautifulSoup(r.text, 'lxml')
            # Priority selector: .artText is most stable on ET
            content = s.select_one('.artText') or s.select_one('.story_art') or s.select_one('.articletext')
            if content:
                # Remove common non-text elements
                for div in content.select('.social_share, .ads, script, style, .related-news-widget'):
                    div.decompose()
                return content.text.strip()[:8000]
        except Exception:
            pass
        return None
