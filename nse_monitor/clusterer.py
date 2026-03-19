import logging
import numpy as np
import pickle
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

class EventClusterer:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        logger.info(f"Initializing Semantic Clusterer with model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.similarity_threshold = 0.82
        self.duplicate_threshold = 0.92

    def get_embedding(self, text):
        """Generates embedding for a given text (headline/summary)."""
        return self.model.encode(text)

    def find_cluster(self, headline, summary, recent_news):
        """
        Compares new headline + summary with recent news items.
        Returns (cluster_id, is_duplicate, match_headline).
        
        recent_news: list of (id, embedding_blob, cluster_id, headline)
        """
        text = f"{headline} {summary}"
        new_embedding = self.get_embedding(text)
        
        if not recent_news:
            return None, False, None

        best_score = -1
        best_match = None

        for row_id, blob, cluster_id, old_headline in recent_news:
            if not blob:
                continue
            
            old_embedding = pickle.loads(blob)
            score = cosine_similarity([new_embedding], [old_embedding])[0][0]
            
            if score > best_score:
                best_score = score
                best_match = (cluster_id, old_headline)

        if best_score >= self.duplicate_threshold:
            logger.info(f"Duplicate detected: '{headline}' matches '{best_match[1]}' (Score: {best_score:.2f})")
            return best_match[0], True, best_match[1]
        
        if best_score >= self.similarity_threshold:
            logger.info(f"Semantic match found: '{headline}' joins cluster {best_match[0]} (Score: {best_score:.2f})")
            return best_match[0], False, best_match[1]

        return None, False, None

    def serialize_embedding(self, embedding):
        """Converts numpy array to blob for DB storage."""
        return pickle.dumps(embedding.astype(np.float32))

    def deserialize_embedding(self, blob):
        """Converts blob back to numpy array."""
        return pickle.loads(blob)
