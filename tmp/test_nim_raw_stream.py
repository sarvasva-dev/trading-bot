import requests
import json
import sys

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"

headers = {
  "Authorization": "Bearer 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",
  "Accept": "text/event-stream"
}

prompt = """
Analyze these 1 news items:
[0] SOURCE: Test | HEADLINE: RELIANCE reports 20% growth in profit | SUMMARY: Reliance Industries has announced a significant increase in its quarterly net profit, beating market expectations.

Output ONLY a JSON list of objects:
[
  {
    "index": 0,
    "score": 80,
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
  "top_p": 0.95,
  "stream": True,
  "chat_template_kwargs": {"enable_thinking": True}
}

print("Sending request to NVIDIA NIM...")
try:
    response = requests.post(invoke_url, headers=headers, json=payload, stream=True, timeout=120)
    print(f"Status: {response.status_code}")
    
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode("utf-8")
            if decoded_line.startswith("data: ") and decoded_line != "data: [DONE]":
                try:
                    chunk_data = json.loads(decoded_line[6:])
                    choices = chunk_data.get("choices", [])
                    if choices and choices[0].get("delta", {}).get("content"):
                        sys.stdout.write(choices[0]["delta"]["content"])
                        sys.stdout.flush()
                except json.JSONDecodeError:
                    pass
    print("\n--- Done ---")
except Exception as e:
    print(f"\nError: {e}")
