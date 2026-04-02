import os
import re

# 🔐 NSE TRADING BOT HARDENING SCRIPT (v1.0)
# This script applies the recommended security patches from the audit report.

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NSE_MONITOR_DIR = os.path.join(BASE_DIR, "nse_monitor")

def patch_file(file_path, search_pattern, replacement):
    if not os.path.exists(file_path):
        print(f"⚠️  Skipping: {file_path} (File not found)")
        return False
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    if search_pattern in content:
        new_content = content.replace(search_pattern, replacement)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"✅ Patched: {os.path.basename(file_path)}")
        return True
    else:
        print(f"ℹ️  Unchanged: {os.path.basename(file_path)} (Pattern not found or already patched)")
        return False

def apply_hardening():
    print("🚀 Starting NSE Bot Security Hardening...\n")

    # 1. config.py: Remove default admin password
    patch_file(
        os.path.join(NSE_MONITOR_DIR, "config.py"),
        'ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123").strip()',
        'ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()'
    )

    # 2. telegram_bot.py: Add Rate Limiting logic
    # (Simplified for demonstration)
    print("ℹ️  Rate limiting check logic should be manually integrated for complex async bots.")

    # 3. database.py: Fix inconsistent default session timeout
    patch_file(
        os.path.join(NSE_MONITOR_DIR, "database.py"),
        "def is_admin_session_valid(self, chat_id, timeout_minutes=43200):",
        "def is_admin_session_valid(self, chat_id, timeout_minutes=60):"
    )

    print("\n✅ Initial Hardening Complete. Please audit the manually reported Critical issues.")

if __name__ == "__main__":
    apply_hardening()
