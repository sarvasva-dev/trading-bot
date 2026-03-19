import os
import sys
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.llm_processor import LLMProcessor

def main():
    print("Testing LLMProcessor.analyze_news_batch with Timer...")
    processor = LLMProcessor()
    
    test_items = [
        {
            'source': 'Test',
            'headline': 'RELIANCE reports 20% growth in profit',
            'summary': 'Reliance Industries has announced a significant increase in its quarterly net profit, beating market expectations.'
        },
        {
            'source': 'Test',
            'headline': 'TCS announces massive dividend payout',
            'summary': 'Tata Consultancy Services has declared a special dividend of Rs 25 per share along with the final dividend.'
        }
    ]
    
    print("Starting analysis... Please wait, Qwen-3.5 might take a while to reason...")
    start_time = time.time()
    
    try:
        results = processor.analyze_news_batch(test_items)
        elapsed = time.time() - start_time
        print(f"\n[SUCCESS] Analysis completed in {elapsed:.2f} seconds.")
        print(f"Results: {results}")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n[FAILED] Analysis failed after {elapsed:.2f} seconds.")
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
