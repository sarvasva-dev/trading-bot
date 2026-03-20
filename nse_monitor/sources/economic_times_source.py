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
        
        # Enhanced Headers to mimic a real browser visit
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://economictimes.indiatimes.com/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

        try:
            # Shift to the specialized news feed for better reliability
            news_url = "https://economictimes.indiatimes.com/markets/stocks/news"
            
            response = requests.get(news_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Updated Selectors based on recent ET layout changes
            # ET often changes class names, so we check multiple common patterns
            news_items = soup.select('.eachStory') or \
                         soup.select('.story-box') or \
                         soup.select('div[data-artid]') or \
                         soup.select('.media-body') or \
                         soup.select('.news-list li')

            # If primary feed fails, try the "Stocks" landing page which is more stable
            if not news_items:
                logger.warning("ET News URL empty/changed, trying Stocks Landing Page fallback...")
                headers["Referer"] = news_url
                time.sleep(1) # Polite pause
                response = requests.get("https://economictimes.indiatimes.com/markets/stocks", headers=headers, timeout=15)
                soup = BeautifulSoup(response.text, 'lxml')
                news_items = soup.select('.eachStory') or \
                             soup.select('.story-box') or \
                             soup.select('.top-news li')

            results = []
            seen_links = set()

            for item in news_items:
                # Limit to 7 items to process
                if len(results) >= 7:
                    break

                title_tag = item.find('h3') or item.find('a') or item.find('h4')
                if not title_tag: continue
                
                headline = title_tag.text.strip()
                if not headline or len(headline) < 10: continue

                # robust link extraction
                link = ""
                if title_tag.name == 'a':
                    link = title_tag.get('href', "")
                elif title_tag.find('a'):
                     link = title_tag.find('a').get('href', "")
                
                if not link: continue

                if not link.startswith('http'):
                    link = "https://economictimes.indiatimes.com" + link
                
                # Check for duplicates within this fetch
                if link in seen_links: continue
                seen_links.add(link)
                
                # Skip multimedia pages (videos/slideshows) and liveblogs (often messy)
                if any(x in link for x in ["/videoshow/", "/slideshow/", "/liveblog/", "/podcast/"]):
                    continue

                # Fetch deeper context for AI
                try:
                    full_text = self._fetch_full_article(link, headers)
                except Exception:
                    full_text = headline

                # Try to extract timestamp
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                try:
                    time_tag = item.find('time')
                    if time_tag and time_tag.has_attr('data-time'):
                         # ET often uses unix timestamp in data-time
                         # Check if it's in milliseconds (13 digits) or seconds (10 digits)
                         unix_time = float(time_tag['data-time'])
                         if unix_time > 1000000000000: unix_time /= 1000
                         timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(unix_time))
                except Exception:
                    pass

                results.append({
                    "source": "Economic Times",
                    "headline": headline,
                    "summary": full_text or headline,
                    "url": link,
                    "timestamp": timestamp
                })
            
            if results:
                logger.info(f"Fetched {len(results)} items from Economic Times.")
            else:
                logger.warning("Fetched 0 items from ET even after fallback.")
                
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
