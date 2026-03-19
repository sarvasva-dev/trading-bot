import os
import sys

# Add project root to path so we can import nse_monitor
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_monitor.llm_processor import LLMProcessor
from nse_monitor.config import LLM_MODEL

def main():
    print("======================================================")
    print(f" NVIDIA NIM DIRECT CHAT TEST (Model: {LLM_MODEL})")
    print("======================================================\n")
    
    try:
        processor = LLMProcessor()
        if not processor.client:
            print("[ERROR] Client not initialized. Check your config.py")
            return

        print("Bot Configuration Loaded. Type 'exit' to quit.")
        print("-" * 30)

        while True:
            user_input = input("\nYou: ")
            if user_input.lower() in ['exit', 'quit', 'q']:
                break
            
            if not user_input.strip():
                continue

            print("\nAnalyzing...", end="\r")
            
            try:
                # Using the exact same call structure as the bot
                response = processor.client.chat.completions.create(
                    model=processor.model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful AI assistant."},
                        {"role": "user", "content": user_input}
                    ],
                    temperature=0.6,
                    top_p=0.95,
                    extra_body={"chat_template_kwargs": {"enable_thinking": True}}
                )
                
                # Check for reasoning field if available in the specific API response
                message = response.choices[0].message
                content = message.content
                
                print(f"\nQwen: {content}")
                
            except Exception as e:
                print(f"\n[ERROR] API Call failed: {e}")
                if "402" in str(e):
                    print("Hint: This is an 'Insufficient Balance' error. Please check your NVIDIA NIM credits.")

    except KeyboardInterrupt:
        print("\nExiting...")

if __name__ == "__main__":
    main()
