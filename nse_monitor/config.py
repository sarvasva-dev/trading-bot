import os
from dotenv import load_dotenv

# Storage Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Project Root (one level up from nse_monitor/)
ROOT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# NSE Constants
NSE_BASE_URL = "https://www.nseindia.com"
NSE_API_URL = f"{NSE_BASE_URL}/api/corporate-announcements"

# Bot Branding
BOT_NAME = "Market Pulse"

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_BOT_TOKEN = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123").strip()

# Support multiple chat IDs (comma-separated)
_chat_ids = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [cid.strip() for cid in _chat_ids.split(",") if cid.strip()]

# AI Config
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()

# Email Config (Notifier)
_alert_emails = os.getenv("ALERT_EMAILS", "")
ALERT_EMAILS = [e.strip() for e in _alert_emails.split(",") if e.strip()]
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Storage Paths
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "processed_announcements.db")

# Modern User-Agents for Rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1"
]

# Base Headers
HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{NSE_BASE_URL}/companies-listing/corporate-filings-announcements",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest"
}

# --- PRODUCTION ALERT CONTROLS ---
# Minimum impact score (0-10) to trigger a Telegram alert
# Set to 7 to filter out noise like ESOPs, routine filings
ALERT_THRESHOLD = 5

# Maximum alerts to send per hour to avoid spamming/Telegram limits
MAX_ALERTS_PER_HOUR = 5

# --- SYSTEM SETTINGS ---
# --- PAYMENT CONFIG (Razorpay) ---
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_placeholder")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "secret_placeholder")

# Dynamic Subscription Plans
def _get_plan(key, default, label):
    val = os.getenv(key, default)
    try:
        p, d = val.split(":")
        return {"amount": int(p), "days": int(d), "label": label}
    except:
        p, d = default.split(":")
        return {"amount": int(p), "days": int(d), "label": label}

SUBSCRIPTION_PLANS = {
    "99": _get_plan("PLAN_99", "99:2", "Market Trial"),
    "499": _get_plan("PLAN_499", "499:7", "Growth Value"),
    "999": _get_plan("PLAN_999", "999:28", "Institutional Pro"),
    "7999": _get_plan("PLAN_7999", "7999:336", "Annual Industry Partner")
}

# --- SCHEDULER CONTROLS ---
DISABLE_SCHEDULER = False # Set to True for manual maintenance modes
