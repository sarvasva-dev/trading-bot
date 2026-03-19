import logging
import difflib

logger = logging.getLogger(__name__)

class SemanticDeduplicator:
    def __init__(self):
        logger.info("Initializing Lightweight Semantic Deduplicator (1GB RAM Optimized)")

    def generate_embedding(self, text):
        """No embeddings needed for lightweight mode."""
        return None

    def is_duplicate(self, text, existing_items, threshold=0.70):
        """
        Calculates similarity using SequenceMatcher (Lightweight).
        existing_items: List of headlines from recent news.
        """
        if not existing_items or not text:
            return False

        text_lower = text.lower()
        for headline in existing_items:
            # Headline might be a tuple (headline, embedding) from DB
            if isinstance(headline, tuple):
                headline = headline[0]
            
            similarity = difflib.SequenceMatcher(None, text_lower, headline.lower()).ratio()
            
            if similarity > threshold:
                logger.info(f"Duplicate detected! '{text}' similarity with '{headline}' is {similarity:.2f}")
                return True
        
        return False
