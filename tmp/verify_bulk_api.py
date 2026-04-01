import asyncio
import os
import sys

# Ensure nse_monitor is in path
sys.path.append(os.getcwd())

from nse_monitor.sources.bulk_deal_source import BulkDealSource

async def main():
    src = BulkDealSource()
    try:
        # Test date: 30 March 2026 (Yesterday in this simulation)
        # The API URL we saw in browser:
        # https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from=30-03-2026&to=31-03-2026
        url = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from=30-03-2026&to=30-03-2026"
        referer = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"

        # Use client for warming up/headers
        data = await src.client.get_json(url, referer=referer)

        if data and data.get("data"):
            item = data["data"][0]
            print(f"Data found! Items: {len(data['data'])}")
            print(f"Keys: {list(item.keys())}")
            print(f"Sample Item: {item}")
        else:
            print(f"No data returned for 30-03-2026. Response: {data}")
    finally:
        await src.client.close()

if __name__ == "__main__":
    asyncio.run(main())
