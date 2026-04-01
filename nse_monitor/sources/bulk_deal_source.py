import logging
import asyncio
from datetime import datetime
import pytz
from nse_monitor.nse_api import NSEClient
from nse_monitor.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)

class BulkDealSource:
    NAME = "NSE_BULK"
    MIN_DEAL_VALUE_CR = 0.1 # v4.3.2: Lowered for ingestion/cache populate. Alerting still 5.0.

    def __init__(self, nse_client=None):
        self.client = nse_client or NSEClient()

    async def fetch(self):
        """Fetches real-time Bulk & Block deals (Async)."""
        if not self.client: return []
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        
        # v7.0: Market Hour Gate
        if not (9 <= now.hour < 16 and now.weekday() < 5): return []

        try:
            date_str = now.strftime("%d-%m-%Y")
            url = f"https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from={date_str}&to={date_str}"
            referer = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
            
            data = await self.client.get_json(url, referer=referer)
            deals = data.get("data", []) if data else []
            results = []

            for deal in deals:
                # Key Mapping for historicalOR endpoint
                symbol = deal.get("BD_SYMBOL", deal.get("symbol", "N/A"))
                qty = deal.get("BD_QTY_TRD", deal.get("quantityTraded", 0)) or 0
                price = deal.get("BD_TP_WATP", deal.get("tradePrice", 0)) or 0
                name = deal.get("BD_CLIENT_NAME", deal.get("clientName", "Unknown"))
                bs = deal.get("BD_BUY_SELL", deal.get("buySellFlag", "BUY"))
                
                try:
                    val_cr = (float(qty) * float(price)) / 1_00_00_000
                except: val_cr = 0

                if val_cr < self.MIN_DEAL_VALUE_CR: continue

                results.append({
                    "source": "NSE_BULK",
                    "headline": f"{symbol}: {name} {bs}s {qty:,} @ ₹{price} (≈₹{val_cr:.1f} Cr)",
                    "symbol": symbol,
                    "summary": f"Bulk/Block: {name} {bs} {qty:,} {symbol} @ ₹{price} (₹{val_cr:.1f} Cr)",
                    "url": referer,
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "deal_value_cr": val_cr,
                    "sentiment": "Bullish" if bs == "BUY" else "Bearish"
                })
            return results
        except Exception as e:
            logger.error(f"Failed to fetch bulk deals: {e}")
            return []

    async def get_deals_for_report(self):
        """v4.2.1: Normalized output with Freshness Gate (Truthful Recap)."""
        expected_date = TradingCalendar.get_previous_trading_day()
        expected_str = expected_date.strftime("%d-%b-%Y") # NSE format: 28-Mar-2025
        
        try:
            date_str = expected_date.strftime("%d-%m-%Y")
            url = f"https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from={date_str}&to={date_str}"
            referer = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
            data = await self.client.get_json(url, referer=referer)
            deals = data.get("data", []) if data else []
            
            actual_date_str = deals[0].get("BD_DT_DATE", "N/A") if deals else "N/A"
            is_stale = actual_date_str != expected_str
            
            results = []
            if not is_stale:
                for d in deals:
                    symbol = d.get("BD_SYMBOL", d.get("symbol", "N/A"))
                    qty = d.get("BD_QTY_TRD", d.get("quantityTraded", 0)) or 0
                    price = d.get("BD_TP_WATP", d.get("tradePrice", 0)) or 0
                    client = d.get("BD_CLIENT_NAME", d.get("clientName", "Unknown"))
                    buy_sell = d.get("BD_BUY_SELL", d.get("buySellFlag", "BUY"))
                    trade_date = d.get("BD_DT_DATE", d.get("date", "N/A"))
                    
                    try:
                        val_cr = (float(qty) * float(price)) / 1_00_00_000
                    except: val_cr = 0
                    
                    results.append({
                        "symbol": symbol,
                        "client_name": client,
                        "buy_sell": buy_sell,
                        "qty": qty,
                        "price": price,
                        "val_cr": val_cr,
                        "trade_date": trade_date
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
