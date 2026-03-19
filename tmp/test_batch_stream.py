import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.llm_processor import LLMProcessor

def main():
    print("Testing LLMProcessor.analyze_news_batch with streaming...")
    processor = LLMProcessor()
    
    test_items = [
        {
            'source': 'Test',
            'headline': 'RELIANCE reports 20% growth in profit',
            'summary': 'Reliance Industries has announced a significant increase in its quarterly net profit, beating market expectations.'
        }
    ]
    
    print("Starting analysis (Streaming)...")
    results = processor.analyze_news_batch(test_items)
    
    print(f"\nAnalysis results: {results}")

if __name__ == "__main__":
    main()
