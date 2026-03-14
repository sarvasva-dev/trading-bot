import requests
import os
from dotenv import load_dotenv

def get_updates():
    # Load .env from the same directory as the script or the parent nse_monitor
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(base_dir, ".env"))
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or "your_token" in token:
        print("Error: Please put your real token in nse_monitor/.env first!")
        return

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    print(f"Checking for updates at {url}...")
    
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        
        if not data.get("ok"):
            print(f"Error from Telegram: {data.get('description')}")
            return

        results = data.get("result", [])
        if not results:
            print("No updates found. Please send a message to your bot or add it to a channel first!")
            return

        print("\n--- Potential Chat IDs Found ---")
        for res in results:
            chat = None
            if "message" in res:
                chat = res["message"]["chat"]
            elif "channel_post" in res:
                chat = res["channel_post"]["chat"]
            elif "my_chat_member" in res:
                chat = res["my_chat_member"]["chat"]

            if chat:
                print(f"Type: {chat.get('type')} | Name: {chat.get('title') or chat.get('username') or 'N/A'} | ID: {chat.get('id')}")
        print("--------------------------------")
        print("\nCopy the ID you need and paste it in TELEGRAM_CHAT_ID in your .env file.")

    except Exception as e:
        print(f"Error connecting to Telegram: {e}")

if __name__ == "__main__":
    get_updates()
