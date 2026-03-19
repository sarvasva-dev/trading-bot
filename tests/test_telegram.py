import os
import requests
from dotenv import load_dotenv

load_dotenv('nse_monitor/.env')

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_ids = os.getenv("TELEGRAM_CHAT_ID", "").split(",")

print(f"Token: '{token}'")
print(f"Chat IDs: {chat_ids}")

if not token:
    print("ERROR: Token not found in .env")
    exit()

base_url = f"https://api.telegram.org/bot{token}/"
print(f"Testing URL: {base_url}getMe")

try:
    r = requests.get(f"{base_url}getMe")
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.json()}")
except Exception as e:
    print(f"Request failed: {e}")
