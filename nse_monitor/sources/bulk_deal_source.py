import logging
import asyncio
from datetime import datetime
import pytz
from nse_monitor.nse_api import NSEClient
from nse_monitor.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)

class BulkDealSource:
    NAME = "NSE_BULK"
    MIN_DEAL_VALUE_CR = 5

    def __init__(self, nse_client=None):
        self.client = nse_client or NSEClient()

    async def fetch(self):
        """Fetches real-time Bulk & Block deals (Async)."""
        if not self.client: return []
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        if not (9 <= now.hour < 16 and now.weekday() < 5): return []

        try:
            url = "https://www.nseindia.com/api/live-analysis-bulk-deal"
            referer = "https://www.nseindia.com/report-search/equities?id=all-daily-reports"
            warmup = "https://www.nseindia.com/report-search/equities"
            data = await self.client.get_json(url, referer=referer, warmup=warmup)
            deals = data.get("data", []) if data else []
            results = []

            for deal in deals:
                symbol = deal.get("symbol", "N/A")
                qty = deal.get("quantityTraded", 0) or 0
                price = deal.get("tradePrice", 0) or 0
                name = deal.get("clientName", "Unknown")
                bs = deal.get("buySellFlag", "BUY")
                val_cr = (qty * price) / 1_00_00_000

                if val_cr < self.MIN_DEAL_VALUE_CR: continue

                results.append({
                    "source": "NSE_BULK",
                    "headline": f"{symbol}: {name} {bs}s {qty:,} @ ₹{price} (≈₹{val_cr:.1f} Cr)",
                    "symbol": symbol,
                    "summary": f"Bulk/Block: {name} {bs} {qty:,} {symbol} @ ₹{price} (₹{val_cr:.1f} Cr)",
                    "url": "https://www.nseindia.com/report-search/equities?id=all-daily-reports",
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "deal_value_cr": val_cr,
                    "sentiment": "Bullish" if bs == "BUY" else "Bearish"
                })
            return results
        except: return []

    async def get_deals_for_report(self):
        """v4.2.1: Normalized output with Freshness Gate (Truthful Recap)."""
        expected_date = TradingCalendar.get_previous_trading_day()
        expected_str = expected_date.strftime("%d-%b-%Y") # NSE format: 28-Mar-2025
        
        try:
            url = "https://www.nseindia.com/api/live-analysis-bulk-deal"
            referer = "https://www.nseindia.com/report-search/equities?id=all-daily-reports"
            warmup = "https://www.nseindia.com/report-search/equities"
            data = await self.client.get_json(url, referer=referer, warmup=warmup)
            deals = data.get("data", []) if data else []
            
            # Resolve actual data date from the first row if available
            actual_date_str = deals[0].get("date", "N/A") if deals else "N/A"
            is_stale = actual_date_str != expected_str
            
            results = []
            if not is_stale:
                for d in deals:
                    qty = d.get("quantityTraded", 0) or 0
                    price = d.get("tradePrice", 0) or 0
                    val_cr = (qty * price) / 1_00_00_000
                    
                    results.append({
                        "symbol": d.get("symbol", "N/A"),
                        "client_name": d.get("clientName", "Unknown"),
                        "buy_sell": d.get("buySellFlag", "BUY"),
                        "qty": qty,
                        "price": price,
                        "val_cr": val_cr,
                        "trade_date": d.get("date", "N/A")
                    })
            
            return {
                "deals": results,
                "recap_date": expected_str,
                "actual_date": actual_date_str,
                "is_stale": is_stale
            }
        except Exception as e:
            logger.error(f"Failed to fetch bulk deals for report: {e}")
            return {"deals": [], "recap_date": expected_str, "actual_date": "N/A", "is_stale": True}
