from nse_monitor.nse_api import NSEClient
import logging

logging.basicConfig(level=logging.INFO)
client = NSEClient()
data = client.get_announcements()
if data and len(data) > 0:
    print("Keys found in announcement:")
    print(data[0].keys())
    print("\nSample values:")
    for k in ['symbol', 'sm_name', 'desc', 'an_dt', 'attchmntFile']:
        print(f"{k}: {data[0].get(k)}")
else:
    print("No data found or request failed.")
