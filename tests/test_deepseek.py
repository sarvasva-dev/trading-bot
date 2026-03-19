import os
import sys

# Add the current directory to sys.path so we can import nse_monitor
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from nse_monitor.llm_processor import LLMProcessor

def test_deepseek_integration():
    print("Testing DeepSeek Integration via LLMProcessor...")
    
    try:
        processor = LLMProcessor()
        if not processor.client:
            print("❌ Failed to initialize LLMProcessor client.")
            return

        company_name = "Test Company Ltd"
        sample_text = """
        Test Company Ltd announces a bonus issue of 1:1. 
        The board has approved the issuance of bonus shares to existing shareholders in the ratio of 1 bonus share for every 1 existing equity share held.
        Record date will be announced later.
        """
        
        print(f"\nAnalyzing sample announcement for {company_name}...")
        result = processor.analyze_news(company_name, sample_text, source_type="corporate")
        
        print("\n--- Analysis Result ---")
        print(result)
        
        if result.get("offline"):
            print("\n❌ Analysis returned offline/fallback response.")
        else:
            print("\n✅ DeepSeek Analysis Successful!")
            print(f"Impact: {result.get('impact')}")
            print(f"Score: {result.get('impact_score')}")

    except Exception as e:
        print(f"\n❌ Exception during test: {e}")

if __name__ == "__main__":
    test_deepseek_integration()
