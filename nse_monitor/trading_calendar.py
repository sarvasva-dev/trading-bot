"""
nse_monitor/trading_calendar.py
v1.0 — Precise Trading Calendar Engine
Handles: NSE Holidays, Weekend Skipping, Accurate Expiry Calculation
"""
import json
import os
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Load holidays once at module level
_HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "data", "nse_holidays.json")

def _load_holidays():
    try:
        with open(_HOLIDAYS_FILE, "r") as f:
            data = json.load(f)
        holidays = set()
        for year_holidays in data.values():
            for d in year_holidays:
                holidays.add(d)  # e.g. "2025-03-14"
        logger.info(f"Trading Calendar: Loaded {len(holidays)} NSE holidays.")
        return holidays
    except Exception as e:
        logger.error(f"Could not load NSE holidays: {e}. Falling back to weekends only.")
        return set()

NSE_HOLIDAYS = _load_holidays()


class TradingCalendar:
    """
    Central calendar engine for Market Pulse v1.0.
    All credit deduction and expiry calculation goes through here.
    """

    @staticmethod
    def is_trading_day(dt=None):
        """
        Returns True if the given date is a valid NSE trading day.
        Checks: Not a weekend, Not an NSE holiday.

        Args:
            dt: datetime.date or datetime.datetime object.
                Defaults to today (IST) if None.
        """
        if dt is None:
            import pytz
            from datetime import datetime
            tz = pytz.timezone("Asia/Kolkata")
            dt = datetime.now(tz).date()

        # Normalize to date object
        if hasattr(dt, 'date'):
            dt = dt.date()

        # Weekend check
        if dt.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return False

        # Holiday check
        dt_str = dt.strftime("%Y-%m-%d")
        if dt_str in NSE_HOLIDAYS:
            logger.info(f"Trading Calendar: {dt_str} is an NSE Holiday. Skipping.")
            return False

        return True

    @staticmethod
    def get_expiry_date(working_days_left, from_date=None):
        """
        Calculates the EXACT calendar date when a user's subscription expires.
        Walks forward through the calendar, skipping weekends and NSE holidays.

        Args:
            working_days_left: integer number of market days remaining
            from_date: start date (defaults to today IST)

        Returns:
            datetime.date of the expiry day
        """
        if from_date is None:
            import pytz
            from datetime import datetime
            tz = pytz.timezone("Asia/Kolkata")
            from_date = datetime.now(tz).date()

        if hasattr(from_date, 'date'):
            from_date = from_date.date()

        days_counted = 0
        current = from_date

        while days_counted < working_days_left:
            current += timedelta(days=1)
            if TradingCalendar.is_trading_day(current):
                days_counted += 1

        return current

    @staticmethod
    def get_holiday_name(dt=None):
        """
        Returns the name of the holiday if today is one, else None.
        Used for the Morning Report 'Holiday Reminder' feature.
        """
        # Static map for display names
        HOLIDAY_NAMES = {
            # 2024
            "2024-01-26": "Republic Day",
            "2024-03-08": "Mahashivratri",
            "2024-03-25": "Holi",
            "2024-03-29": "Good Friday",
            "2024-04-11": "Id-Ul-Fitr (Eid)",
            "2024-04-17": "Ram Navami",
            "2024-05-01": "Maharashtra Day",
            "2024-06-17": "Bakri Eid",
            "2024-07-17": "Muharram",
            "2024-08-15": "Independence Day",
            "2024-10-02": "Gandhi Jayanti",
            "2024-11-01": "Diwali (Laxmi Pujan)",
            "2024-11-15": "Gurunanak Jayanti",
            "2024-12-25": "Christmas",
            # 2025
            "2025-02-26": "Mahashivratri",
            "2025-03-14": "Holi",
            "2025-03-31": "Id-Ul-Fitr (Eid)",
            "2025-04-10": "Mahavir Jayanti",
            "2025-04-14": "Dr. Ambedkar Jayanti",
            "2025-04-18": "Good Friday",
            "2025-05-01": "Maharashtra Day",
            "2025-08-15": "Independence Day",
            "2025-08-27": "Ganesh Chaturthi",
            "2025-10-02": "Gandhi Jayanti / Dussehra",
            "2025-10-21": "Diwali (Laxmi Pujan)",
            "2025-10-22": "Diwali (Balipratipada)",
            "2025-11-05": "Guru Nanak Jayanti",
            "2025-12-25": "Christmas",
        }

        if dt is None:
            import pytz
            from datetime import datetime
            tz = pytz.timezone("Asia/Kolkata")
            dt = datetime.now(tz).date()

        if hasattr(dt, 'date'):
            dt = dt.date()

        dt_str = dt.strftime("%Y-%m-%d")
        return HOLIDAY_NAMES.get(dt_str, None)

    @staticmethod
    def get_next_trading_day(from_date=None):
        """Returns the next valid trading day from a given date."""
        if from_date is None:
            import pytz
            from datetime import datetime
            tz = pytz.timezone("Asia/Kolkata")
            from_date = datetime.now(tz).date()

        if hasattr(from_date, 'date'):
            from_date = from_date.date()

        current = from_date + timedelta(days=1)
        while not TradingCalendar.is_trading_day(current):
            current += timedelta(days=1)
        return current

    @staticmethod
    def sync_from_nse():
        """v1.3: Fetches the latest holiday list from NSE API and updates the local JSON."""
        import requests
        from datetime import datetime
        url = "https://www.nseindia.com/api/holiday-master?type=trading"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays"
        }
        try:
            # 1. Get Session
            session = requests.Session()
            session.get("https://www.nseindia.com", headers=headers, timeout=10)
            
            # 2. Get Holidays
            r = session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            
            # 3. Parse and Save
            # NSE returns a list of years. We want the current 'trading' list.
            clean_data = {}
            for row in data.get('CM', []): # Cash Market
                d_str = datetime.strptime(row['tradingDate'], "%d-%b-%Y").strftime("%Y-%m-%d")
                year = d_str.split("-")[0]
                if year not in clean_data: clean_data[year] = []
                clean_data[year].append(d_str)
            
            if clean_data:
                with open(_HOLIDAYS_FILE, "w") as f:
                    json.dump(clean_data, f, indent=4)
                
                # Reload global set
                global NSE_HOLIDAYS
                NSE_HOLIDAYS = _load_holidays()
                logger.info("✅ Trading Calendar: Successfully synced with NSE.")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to sync holidays from NSE: {e}")
            return False
