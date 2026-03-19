import requests
import json

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"

headers = {
  "Authorization": "Bearer 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",
  "Accept": "application/json"
}

payload = {
  "model": "qwen/qwen3.5-122b-a10b",
  "messages": [{"role":"user","content":"Hi, what model are you?"}],
  "max_tokens": 100,
  "temperature": 0.6,
  "top_p": 0.95,
  "chat_template_kwargs": {"enable_thinking": True}
}

response = requests.post(invoke_url, headers=headers, json=payload)
print(f"Status: {response.status_code}")
print(response.text)
