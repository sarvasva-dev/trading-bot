import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import anthropic
except ImportError:
    print("Anthropic library not found. Please install it using 'pip install anthropic'.")
    sys.exit(1)

# The key provided by the user
API_KEY = "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"

def test_claude_haiku():
    print(f"Testing Claude 3 Haiku API Key...")
    
    try:
        client = anthropic.Anthropic(api_key=API_KEY)
        
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            temperature=0,
            messages=[
                {"role": "user", "content": "Hello, respond with 'API Working' if you receive this."}
            ]
        )
        
        print("\nResponse from Claude:")
        print(message.content[0].text)
        print("\nSUCCESS: The API key is valid and Claude Haiku is responding.")
        return True
        
    except anthropic.AuthenticationError:
        print("\nERROR: Authentication failed. The API key is invalid.")
    except anthropic.PermissionError:
        print("\nERROR: Permission denied. The key might not have access to this model.")
    except Exception as e:
        print(f"\nERROR: An unexpected error occurred: {e}")
    
    return False

if __name__ == "__main__":
    test_claude_haiku()
