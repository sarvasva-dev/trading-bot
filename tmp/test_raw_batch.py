import requests
import json

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"

headers = {
  "Authorization": "Bearer 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",
  "Accept": "application/json"
}

# The exact prompt structure from llm_processor.py
prompt = """
Analyze these 1 news items:
[0] SOURCE: Test | HEADLINE: RELIANCE reports 20% growth in profit | SUMMARY: Reliance Industries has announced a significant increase in its quarterly net profit, beating market expectations.

Output ONLY a JSON list of objects:
[
  {
    "index": 0,
    "score": (0-100),
    "sentiment": "Positive/Negative/Neutral",
    "impact": "Brief explanation",
    "is_duplicate": false
  }
]
"""

payload = {
  "model": "qwen/qwen3.5-122b-a10b",
  "messages": [
      {"role": "system", "content": "You are a professional financial analyst who only outputs valid JSON."},
      {"role": "user", "content": prompt}
  ],
  "max_tokens": 1000,
  "temperature": 0.6,
  "top_p": 0.95
}

print("Sending request...")
try:
    response = requests.post(invoke_url, headers=headers, json=payload, timeout=60)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
