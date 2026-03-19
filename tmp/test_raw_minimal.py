import requests
import json

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"

headers = {
  "Authorization": "Bearer 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",
  "Accept": "application/json"
}

payload = {
  "model": "qwen/qwen3.5-122b-a10b",
  "messages": [{"role":"user","content":"HI"}],
  "max_tokens": 50,
  "temperature": 0.6
}

print("Sending minimal request...")
try:
    response = requests.post(invoke_url, headers=headers, json=payload, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
