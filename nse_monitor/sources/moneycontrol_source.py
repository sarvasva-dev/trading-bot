import logging
import requests
from bs4 import BeautifulSoup
import time
import random
from nse_monitor.config import USER_AGENTS

logger = logging.getLogger(__name__)

class MoneycontrolSource:
    NAME = "MoneyControl"

    def __init__(self):
        self.url = "https://www.moneycontrol.com/news/business/markets/"

    def fetch(self):
        """Scrapes latest market news and full article content from Moneycontrol."""
        logger.info("Fetching data from Moneycontrol Source...")
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            response = requests.get(self.url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            # Updated selector for the latest news list container
            # Added multiple fallback selectors for different page layouts
            news_list = soup.select('#cagetory li.clearfix') or \
                        soup.select('.cagetory li.clearfix') or \
                        soup.select('.latest_news li') or \
                        soup.select('li.clearfix')
            
            results = []
            for item in news_list[:5]: # Top 5 fresh items
                # Focus on h2 as identified in DOM inspection
                title_tag = item.find('h2') or item.find('a')
                if not title_tag: continue
                
                headline = title_tag.text.strip()
                link = title_tag.find('a')['href'] if title_tag.find('a') else ""
                if not link:
                    link_tag = item.find('a', href=True)
                    link = link_tag['href'] if link_tag else ""
                    
                if not link.startswith('http'):
                    link = "https://www.moneycontrol.com" + link
                    
                # Scrape full article content for rich AI sentiment analysis
                full_text = self._fetch_full_article(link, headers)

                # Try to find date in the article
                article_date = time.strftime("%Y-%m-%d %H:%M:%S") # Default to now
                try:
                    date_span = item.find('span', class_='gary-txt')
                    if date_span:
                        # Format example: 'March 19, 2024 09:30 AM IST'
                        raw_date = date_span.text.strip()
                        # Simple parsing or keeping as string for now if consistent
                        # For robustness, we'll stick to now() if parsing fails, but 
                        # future improvement can parse 'raw_date'
                        pass 
                except:
                    pass

                results.append({
                    "source": "Moneycontrol",
                    "headline": headline,
                    "summary": full_text or headline,
                    "url": link,
                    "timestamp": article_date # Using publication time if possible
                })
            
            logger.info(f"Fetched {len(results)} items from Moneycontrol (Latest and Deep).")
            return results
        except Exception as e:
            logger.error(f"Moneycontrol Source fetch failed: {e}")
            return []

    def _fetch_full_article(self, url, headers):
        """Fetches the actual article body for better AI analysis."""
        try:
            r = requests.get(url, headers=headers, timeout=10)
            s = BeautifulSoup(r.text, 'lxml')
            # Priority selectors: #contentdata is most stable
            content = s.select_one('#contentdata') or s.select_one('.content_wrapper') or s.select_one('.article_fullbody')
            if content:
                # Remove ads, social, and redundant elements
                for div in content.select('.social_share, .ads, script, style, .related_news'):
                    div.decompose()
                return content.text.strip()[:8000]
        except Exception:
            pass
        return None
