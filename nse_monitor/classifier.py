import logging

logger = logging.getLogger(__name__)

class NewsClassifier:
    def __init__(self):
        self.categories = {
            "Global Cues": ["us", "asia", "global", "fed", "nasdaq", "dow", "nikkei", "inflation", "oil", "crude"],
            "Major Indian News": ["rbi", "government", "policy", "cabinet", "tax", "gst", "nifty", "sensex", "ministry"],
            "Key Events": ["cpi", "gdp", "earnings", "results", "data release", "economic data", "fii", "dii"],
            "Indian Stocks in News": [] # Fallback category if it doesn't fit others but has a clear focus
        }

    def classify(self, headline, summary=""):
        text = f"{headline} {summary}".lower()
        
        # Priority order
        if any(keyword in text for keyword in self.categories["Global Cues"]):
            return "Global Cues"
            
        if any(keyword in text for keyword in self.categories["Major Indian News"]):
            return "Major Indian News"
            
        if any(keyword in text for keyword in self.categories["Key Events"]):
            return "Key Events"
            
        # If it contains "NSE" or specific symbols/company patterns, it's likely stock news
        return "Indian Stocks in News"

    def extract_ticker(self, text):
        """Attempts to extract a stock ticker/symbol from text."""
        import re
        # Look for uppercase symbols like RELIANCE, HDFCBANK or patterns like (TICKER)
        # 1. Look for patterns in parentheses: (HDFCBANK)
        symbols = re.findall(r'\(([A-Z0-9]{3,})\)', text)
        if symbols:
            return symbols[0].upper()
            
        # 2. Look for common all-caps words that look like tickers at the start of headline
        # Patterns like: RELIANCE: Q3 results... or HDFC Bank shares...
        words = text.split()
        for word in words[:3]: # Usually in first few words
            clean_word = re.sub(r'[^A-Z0-9]', '', word)
            if len(clean_word) >= 3 and clean_word.isupper():
                return clean_word
                
        return None
