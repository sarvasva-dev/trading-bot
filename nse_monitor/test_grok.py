import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

def test_grok():
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL", "grok-4-latest")
    url = "https://api.x.ai/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "messages": [
            {
                "role": "system",
                "content": "You are a test assistant."
            },
            {
                "role": "user",
                "content": "Testing. Just say hi and hello world and nothing else."
            }
        ],
        "model": model,
        "stream": False,
        "temperature": 0
    }
    
    print(f"Testing xAI API with model: {model}")
    print(f"URL: {url}")
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_grok()
