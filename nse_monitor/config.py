import time
import os
from dotenv import load_dotenv

# v4.2.1: Institutional Intelligence Configuration
# Final Industrialized Version

# 1. Global Uptime & Path Logic
START_TIME = time.time()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"), override=True)

# 2. NSE & Bot Identity
NSE_BASE_URL = "https://www.nseindia.com"
NSE_API_URL = f"{NSE_BASE_URL}/api/corporate-announcements"
BOT_NAME = "Bulkbeat TV"

# 3. Connectivity (Telegram & Admin)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_BOT_TOKEN = os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
TELEGRAM_DOCUMENT_TIMEOUT_SEC = int(os.getenv("TELEGRAM_DOCUMENT_TIMEOUT_SEC", 45))

# v2.1: Multiple Admin Support
_admin_ids = os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
TELEGRAM_ADMIN_CHAT_IDS = [cid.strip() for cid in _admin_ids.split(",") if cid.strip()]
# Also include single admin chat ID in the list
if TELEGRAM_ADMIN_CHAT_ID and TELEGRAM_ADMIN_CHAT_ID not in TELEGRAM_ADMIN_CHAT_IDS:
    TELEGRAM_ADMIN_CHAT_IDS.append(TELEGRAM_ADMIN_CHAT_ID)

# v2.0: Secure Authentication (Bcrypt)
# Place the output of scripts/generate_hash.py into the environment
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
ADMIN_SESSION_TIMEOUT_MINUTES = int(os.getenv("ADMIN_SESSION_TIMEOUT_MINUTES", 60))

_chat_ids = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [cid.strip() for cid in _chat_ids.split(",") if cid.strip()]

# 4. Intelligence Engines (AI & Email)
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()

_alert_emails = os.getenv("ALERT_EMAILS", "")
ALERT_EMAILS = [e.strip() for e in _alert_emails.split(",") if e.strip()]
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# 5. Storage & Persistence
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "processed_announcements.db")
PID_FILE_NAME = os.getenv("PID_FILE_NAME", "nsebot.pid").strip() or "nsebot.pid"

# 6. Network & Anti-Bot Infrastructure
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1"
]

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{NSE_BASE_URL}/companies-listing/corporate-filings-announcements",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest"
}

# 7. Alert & Policy Controls (V4.0 Ultra-Strict Mode)
ALERT_THRESHOLD = 5
MAX_ALERTS_PER_HOUR = 5
DISABLE_SCHEDULER = False

ALERT_POLICY_MODE = os.getenv("ALERT_POLICY_MODE", "SENSITIVE_7PLUS")
DAILY_ALERT_SOFT_TARGET = int(os.getenv("DAILY_ALERT_SOFT_TARGET", 5))
DAILY_ALERT_HARD_CAP = int(os.getenv("DAILY_ALERT_HARD_CAP", 10))
SYMBOL_COOLDOWN_MIN = int(os.getenv("SYMBOL_COOLDOWN_MIN", 90))
NEUTRAL_BLOCK = int(os.getenv("NEUTRAL_BLOCK", 1))
ALLOWED_LIVE_SOURCES = os.getenv("ALLOWED_LIVE_SOURCES", "NSE,NSE_SME,NSE_BULK").split(",")
TELEGRAM_SEND_PDF = False

# 8. Bulk Intelligence Policy (V4.2.1)
BULK_REPORT_MIN_VAL_CR = int(os.getenv("BULK_REPORT_MIN_VAL_CR", 5))
BULK_MAX_ITEMS_REPORT = int(os.getenv("BULK_MAX_ITEMS_REPORT", 5))

KNOWN_INSTITUTIONS = [
    "RELIANCE", "SBI", "HDFC", "ICICI", "LIC OF INDIA", "VANGUARD", 
    "BLACKROCK", "MORGAN STANLEY", "GOLDMAN SACHS", "JP MORGAN",
    "FIDELITY", "NORGES BANK", "GIC", "TEMASEK", "TATA SONS", "PRUDENTIAL",
    "AXIS BANK", "KOTAK", "NOMURA", "SOCIETE GENERALE", "BNP PARIBAS"
]

# 9. Payment & Monetization
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_placeholder")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "secret_placeholder")

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
