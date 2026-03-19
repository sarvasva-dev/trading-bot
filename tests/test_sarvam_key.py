from sarvamai import SarvamAI
import os

# Key provided by user
API_KEY = "sk_m2lt55jk_LvxJ8hWcocMtUyDkDigLCLXs"

def test_sarvam():
    print(f"Testing Sarvam AI Key...")
    
    try:
        client = SarvamAI(api_subscription_key=API_KEY)
        
        response = client.chat.completions(
            model="sarvam-30b",
            messages=[
                {"role": "user", "content": "Hey, confirm you are working."}
            ]
        )
        
        print("\nResponse from Sarvam:")
        print(response)
        print("\nSUCCESS: Sarvam AI API is working!")
        return True
        
    except Exception as e:
        print(f"\nERROR: Sarvam failed: {e}")
        return False

if __name__ == "__main__":
    test_sarvam()