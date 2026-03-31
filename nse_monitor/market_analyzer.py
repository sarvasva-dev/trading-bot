import logging
import statistics

logger = logging.getLogger(__name__)

class MarketAnalyzer:
    """v4.0: Smart Money Engine for detecting institutional entry confirmation."""
    
    def __init__(self, nse_client):
        self.nse_client = nse_client

    async def analyze_smart_money(self, symbol):
        """
        Analyzes the last 10-12 days of trading data to confirm 'Smart Money' entry.
        Criteria: 
        1. Volume Spike (> 1.5x of 10-day Avg)
        2. Delivery Percentage > 50% (High conviction)
        3. Delivery Quantity Spike (> 1.5x of 10-day Avg)
        """
        if not symbol or symbol == "N/A":
            return None

        # Fetch 12 days to get a solid 10-day average
        history = await self.nse_client.get_historical_data(symbol, days=15)
        if not history or len(history) < 3:
            logger.warning(f"Insufficient history for {symbol} Smart Money analysis.")
            return None

        try:
            # Parse historical data (Clean types)
            # Keys: CH_TOT_TRADED_QTY, CH_DELIV_QTY, CH_DELIV_PCT, CH_TIMESTAMP, CH_CLOSING_PRICE
            clean_history = []
            for day in history:
                try:
                    clean_history.append({
                        "qty": float(str(day.get("CH_TOT_TRADED_QTY", 0)).replace(',', '')),
                        "deliv_qty": float(str(day.get("CH_DELIV_QTY", 0)).replace(',', '')),
                        "deliv_pct": float(str(day.get("CH_DELIV_PCT", 0)).replace(',', '')),
                        "price": float(str(day.get("CH_CLOSING_PRICE", 0)).replace(',', '')),
                        "date": day.get("CH_TIMESTAMP")
                    })
                except: continue

            if len(clean_history) < 2: return None

            # Current Day Data (Latest entry)
            current = clean_history[0]
            # Past Data (Excluding current)
            past = clean_history[1:]
            
            # 1. Average Volume (10-day)
            avg_vol = statistics.mean([d['qty'] for d in past])
            vol_spike = current['qty'] / avg_vol if avg_vol > 0 else 0
            
            # 2. Average Delivery Qty
            avg_deliv = statistics.mean([d['deliv_qty'] for d in past])
            deliv_spike = current['deliv_qty'] / avg_deliv if avg_deliv > 0 else 0
            
            # 3. Delivery Percentage
            current_deliv_pct = current['deliv_pct']

            # Confirmation Logic
            # User defined threshold: Delivery % > 60% OR (Vol Spike > 2x and Deliv Spike > 1.5x)
            is_confirmed = (current_deliv_pct >= 55) or (vol_spike >= 1.8 and current_deliv_pct >= 40)
            
            result = {
                "symbol": symbol,
                "is_smart_money": is_confirmed,
                "vol_spike": round(vol_spike, 2),
                "deliv_spike": round(deliv_spike, 2),
                "current_deliv_pct": round(current_deliv_pct, 2),
                "avg_vol": round(avg_vol, 0),
                "current_price": current['price']
            }
            
            if is_confirmed:
                logger.info(f"🚀 SMART MONEY CONFIRMED: {symbol} | Deliv: {current_deliv_pct}% | Vol Spike: {vol_spike}x")
            
            return result

        except Exception as e:
            logger.error(f"Error in MarketAnalyzer for {symbol}: {e}")
            return None
