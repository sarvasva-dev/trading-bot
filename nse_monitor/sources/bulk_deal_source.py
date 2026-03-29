import logging
import time
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


class BulkDealSource:
    """
    v1.0: Real-time NSE Bulk & Block Deal fetcher.
    Uses the NSE live-analysis API (same session as main client — bypasses blocks).
    """
    NAME = "NSE_BULK"

    # These thresholds define what counts as "institutionally significant"
    MIN_DEAL_VALUE_CR = 5  # Only deals with value > 5 Cr

    def __init__(self, nse_client=None):
        self.client = nse_client  # Injected from main engine

    def fetch(self):
        """
        Fetches real-time Bulk & Block deals from NSE.
        Returns significant deals as news items for the morning report.
        Only runs during market hours; returns [] otherwise.
        """
        if not self.client:
            logger.warning("BulkDealSource: No NSE client injected. Skipping.")
            return []

        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        # Bulk deals only exist during market hours
        if not (9 <= now.hour < 16 and now.weekday() < 5):
            logger.info("BulkDealSource: Market closed. Skipping bulk deal fetch.")
            return []

        try:
            url = "https://www.nseindia.com/api/live-analysis-bulk-deal"
            referer = "https://www.nseindia.com/report-search/equities?id=all-daily-reports"
            warmup = "https://www.nseindia.com/report-search/equities"

            data = self.client.get_json(url, referer=referer, warmup=warmup)
            if not data:
                logger.warning("BulkDealSource: NSE returned no data.")
                return []

            deals = data.get("data", [])
            results = []

            for deal in deals:
                symbol = deal.get("symbol", "N/A")
                qty = deal.get("quantityTraded", 0) or 0
                price = deal.get("tradePrice", 0) or 0
                client_name = deal.get("clientName", "Unknown")
                buy_sell = deal.get("buySellFlag", "BUY")

                # Calculate approximate deal value in Crores
                deal_value_cr = (qty * price) / 1_00_00_000

                if deal_value_cr < self.MIN_DEAL_VALUE_CR:
                    continue

                sentiment = "Bullish" if buy_sell == "BUY" else "Bearish"
                headline = (
                    f"{symbol}: {client_name} {buy_sell}s "
                    f"{qty:,} shares @ ₹{price:.2f} "
                    f"(≈₹{deal_value_cr:.1f} Cr)"
                )

                results.append({
                    "source": "NSE_BULK",
                    "headline": headline,
                    "symbol": symbol,
                    "summary": (
                        f"Bulk/Block Deal: {client_name} executed a {buy_sell} order "
                        f"for {qty:,} shares of {symbol} at ₹{price:.2f}. "
                        f"Approximate deal value: ₹{deal_value_cr:.1f} Crore. Sentiment: {sentiment}."
                    ),
                    "url": "https://www.nseindia.com/report-search/equities?id=all-daily-reports",
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "deal_value_cr": deal_value_cr,
                    "sentiment": sentiment
                })

            logger.info(f"BulkDealSource: Found {len(results)} significant deals (>{self.MIN_DEAL_VALUE_CR} Cr).")
            return results

        except Exception as e:
            logger.error(f"BulkDealSource fetch failed: {e}")
            return []

    def get_deals_for_report(self):
        """
        Returns a formatted list of today's top 8 bulk/block deals for
        inclusion in the Morning Intelligence Report.
        """
        if not self.client:
            return []
        try:
            url = "https://www.nseindia.com/api/live-analysis-bulk-deal"
            data = self.client.get_json(
                url,
                referer="https://www.nseindia.com/report-search/equities?id=all-daily-reports",
                warmup="https://www.nseindia.com/report-search/equities"
            )
            if not data:
                return []
            return data.get("data", [])[:8]
        except Exception as e:
            logger.error(f"BulkDealSource report fetch failed: {e}")
            return []
