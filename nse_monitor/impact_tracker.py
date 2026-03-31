import asyncio
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class ImpactTracker:
    """v4.0: Instrument for tracking market reaction after a signal dispatch."""
    
    def __init__(self, db, nse_client):
        self.db = db
        self.nse_client = nse_client

    async def start_tracking(self, news_id, symbol, score, sentiment):
        """Initializes tracking for a newly dispatched signal."""
        try:
            # 1. Capture Base Price (Snapshot 0)
            start_price = await self._fetch_price(symbol)
            if not start_price:
                logger.warning(f"Could not fetch start price for {symbol}. Tracking aborted.")
                return

            # 2. Initialize DB Log
            with self.db.conn:
                cursor = self.db.conn.execute(
                    """INSERT INTO alert_dispatch_log 
                       (news_id, symbol, score, sentiment, price_start) 
                       VALUES (?, ?, ?, ?, ?)""",
                    (news_id, symbol, score, sentiment, start_price)
                )
                log_id = cursor.lastrowid

            logger.info(f"📊 Tracking Impact for {symbol} (Start: ₹{start_price})")

            # 3. Schedule Snapshots in background
            asyncio.create_task(self._delayed_snapshot(log_id, symbol, 15, "price_15m"))
            asyncio.create_task(self._delayed_snapshot(log_id, symbol, 60, "price_60m"))
            # EOD check is usually handled by a separate daily maintenance task, 
            # but we can schedule a long-wait for intraday closures.
            
        except Exception as e:
            logger.error(f"ImpactTracker Error for {symbol}: {e}")

    async def _delayed_snapshot(self, log_id, symbol, minutes, column):
        """Waits N minutes and captures a price snapshot."""
        wait_seconds = minutes * 60
        await asyncio.sleep(wait_seconds)
        
        price = await self._fetch_price(symbol)
        if price:
            try:
                with self.db.conn:
                    self.db.conn.execute(
                        f"UPDATE alert_dispatch_log SET {column} = ? WHERE id = ?",
                        (price, log_id)
                    )
                logger.info(f"📍 Impact Snapshot ({minutes}m) for {symbol}: ₹{price}")
            except Exception as e:
                logger.error(f"Failed to update {column} for {symbol}: {e}")

    async def _fetch_price(self, symbol):
        """Fetches the current market price from NSE Quote API."""
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
        referer = f"https://www.nseindia.com/get-quotes/equity?symbol={symbol.upper()}"
        
        data = await self.nse_client.get_json(url, referer=referer)
        if not data: return None
        
        try:
            # v4.0: Extract last price from metadata or priceinfo
            price = data.get("priceInfo", {}).get("lastPrice")
            if not price:
                price = data.get("metadata", {}).get("lastPrice")
            return float(str(price).replace(',', '')) if price else None
        except:
            return None
