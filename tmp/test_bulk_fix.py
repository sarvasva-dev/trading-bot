import asyncio
import logging
import os
import sys

sys.path.append(os.getcwd())

from nse_monitor.nse_api import NSEClient
from nse_monitor.sources.bulk_deal_source import BulkDealSource

logging.basicConfig(level=logging.INFO)

async def test_bulk_deals():
    client = NSEClient()
    source = BulkDealSource(nse_client=client)
    
    print("Fetching today's bulk deals...")
    deals = await source.fetch()
    
    if deals:
        print(f"Success! Found {len(deals)} deals.")
        for d in deals[:3]:
            print(f"- {d['headline']}")
    else:
        print("No deals found (Market might be closed or data not yet updated).")
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(test_bulk_deals())
