import logging
import requests
import time
import html
import os
import json
import pytz
import asyncio
from datetime import datetime, timedelta
from nse_monitor.config import BOT_NAME, ADMIN_PASSWORD, TELEGRAM_DOCUMENT_TIMEOUT_SEC
from nse_monitor.payment_processor import RazorpayProcessor

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, db=None, nse_client=None):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = db
        self.nse_client = nse_client
        self.payment_processor = RazorpayProcessor()
        self.chat_ids = [] # Use list for append/ordering
        self.dynamic_ids_file = "data/dynamic_chat_ids.json"
        self.admin_sessions = {} # chat_id: timestamp
        self.last_update_id = 0 # Track Telegram offsets
        self.ist = pytz.timezone("Asia/Kolkata")
        self._load_dynamic_ids()
        self._sync_with_db()
        self._sync_telegram_offset() # v2.0: Prevent startup "vomit"
        self._clear_webhook()
        self.set_my_commands()

    def _sync_telegram_offset(self):
        """Rule #24: Fetches the latest update_id from Telegram on boot to skip stale messages."""
        if not self.token: return
        try:
            url = f"{self.base_url}/getUpdates"
            # Get only the last message
            r = requests.get(url, params={"limit": 1, "offset": -1}, timeout=5)
            data = r.json()
            if data.get("ok") and data.get("result"):
                self.last_update_id = data["result"][0]["update_id"]
                logger.info(f"Telegram Bot: Boot sync complete. Offset set to {self.last_update_id}.")
        except Exception as e:
            logger.warning(f"Telegram Bot: Failed to sync offset on boot: {e}")

    def _clear_webhook(self):
        """Ensure getUpdates polling is not blocked by an active webhook."""
        if not self.token:
            return
        try:
            url = f"{self.base_url}/deleteWebhook"
            requests.post(url, json={"drop_pending_updates": False}, timeout=8)
            logger.info("Telegram Bot: Webhook cleared for long-polling mode.")
        except Exception as e:
            logger.warning(f"Telegram Bot: deleteWebhook failed: {e}")

    def set_my_commands(self):
        """Sets the unified blue menu buttons in the Telegram UI."""
        if not self.token: return
        commands = [
            {"command": "start", "description": "🚀 Activate Engine & Menu"},
            {"command": "plan", "description": "💎 My Subscription & Expiry"},
            {"command": "hisab", "description": "📝 View Billing Logs (Hisab)"},
            {"command": "subscribe", "description": "🛒 Recharge / Upgrade"},
            {"command": "bulk", "description": "📈 Today's Big Deals"},
            {"command": "upcoming", "description": "🗓️ Corporate Calendar"},
            {"command": "support", "description": "🛠️ Contact Admin (WhatsApp)"}
        ]
        url = f"{self.base_url}/setMyCommands"
        try:
            requests.post(url, json={"commands": commands}, timeout=5)
            logger.info("Telegram Command Menu (Blue Button) updated.")
        except Exception as e:
            logger.error(f"Failed to set commands: {e}")

    def _load_dynamic_ids(self):
        """Loads IDs from JSON storage."""
        if os.path.exists(self.dynamic_ids_file):
            try:
                with open(self.dynamic_ids_file, "r") as f:
                    data = json.load(f)
                    extra_ids = data if isinstance(data, list) else data.get("ids", [])
                    for cid in extra_ids:
                        cid_str = str(cid)
                        if cid_str not in self.chat_ids:
                            self.chat_ids.append(cid_str)
            except Exception as e:
                logger.error(f"Error loading dynamic chat IDs: {e}")

    def _sync_with_db(self):
        """Ensures all JSON IDs are also persisted in the SQLite users table."""
        if not self.db: return
        logger.info("Syncing User Database...")
        try:
            self.db.cleanup_legacy_names()
        except Exception:
            pass
        for chat_id in self.chat_ids:
            self.db.ensure_user(chat_id)

    def _save_dynamic_ids(self, chat_id=None, first_name=None, username=None):
        """Saves a new user to both JSON and DB (Rule #24)."""
        if chat_id and str(chat_id) not in self.chat_ids:
            self.chat_ids.append(str(chat_id))
            if self.db:
                self.db.save_user(chat_id, first_name, username)

        os.makedirs(os.path.dirname(self.dynamic_ids_file), exist_ok=True)
        try:
            with open(self.dynamic_ids_file, "w") as f:
                json.dump(list(set([str(cid) for cid in self.chat_ids])), f)
        except Exception as e:
            logger.error(f"Error saving dynamic IDs: {e}")

    def register_menu_commands(self):
        """Alias for set_my_commands to prevent overwriting."""
        self.set_my_commands()

    def _run_async(self, coro):
        """Run async NSE client calls safely from sync bot handlers."""
        try:
            return asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Async bridge error: {e}")
            return None

    def _clean_name(self, name):
        if not name or name in ("Sync_Legacy", "Legacy", "manual_entry", "Unknown"):
            return "User"
        return name

    def handle_updates(self):
        """Checks for new messages and handles commands via Long Polling."""
        if not self.token: return
        
        try:
            url = f"{self.base_url}/getUpdates"
            # Fix 2: Proper Long-Polling with 20s timeout instead of CPU-burning 1s loops
            params = {"offset": self.last_update_id + 1, "timeout": 20}
            r = requests.get(url, params=params, timeout=25)
            data = r.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    self.last_update_id = update["update_id"]
                    if "message" in update:
                        chat_id = str(update["message"]["chat"]["id"])
                        text = update["message"].get("text", "").strip()
                        first_name = update["message"]["from"].get("first_name", "User")
                        username = update["message"]["from"].get("username", "Unknown")
                            # 1. Registration & Campaign Tracking (v1.3.1)
                        if chat_id not in self.chat_ids:
                            
                            # Parse Campaign Tag: /start <camp_tag>
                            source_tag = "direct"
                            if text.startswith("/start "):
                                parts = text.split()
                                if len(parts) >= 2:
                                    source_tag = parts[1]
                                    logger.info(f"Campaign Detected: User {chat_id} from {source_tag}")

                            is_new = self.db.save_user(chat_id, first_name, username, source=source_tag) if self.db else False
                            self.chat_ids.append(chat_id)
                            
                            if is_new:
                                logger.info(f"New Institutional User Registered: {first_name} | Tag: {source_tag}")
                                self._send_raw(chat_id, "🤝 <b>Professional Onboarding Complete.</b>\n"
                                                      "Welcome to the Market Pulse Institutional Engine. "
                                                      "As a new user, you've been granted <b>2 Free Market-Days</b> of high-impact analysis.")
                            else:
                                self.db.sync_user(chat_id, first_name, username)
                                logger.info(f"Existing User Re-synced: {chat_id}")

                        # Keep profile fields fresh for existing legacy users too
                        if self.db:
                            self.db.sync_user(chat_id, first_name, username)

                        # 2. Command Router
                        if text.startswith("/start"):
                            self._send_welcome(chat_id, first_name)
                        elif text == "/plan" or text == "/me":
                            self._handle_plan(chat_id, first_name)
                        elif text == "/subscribe":
                            self._handle_subscribe_menu(chat_id)
                        elif text == "/history":
                            self._handle_history(chat_id)
                        elif text == "/hisab" or text == "/billing":
                            self._handle_billing_history(chat_id)
                        elif text.startswith("/sub_"):
                            self._handle_plan_selection(chat_id, text, first_name)
                        elif text == "/support":
                            self._send_raw(chat_id, "🛠️ <b>Contact Support</b>\nClick the button below to message the owner on WhatsApp.",
                                          {"inline_keyboard": [[{"text": "📲 Message on WhatsApp", "url": "https://wa.me/917985040858"}]]})
                        elif text == "/verify":
                            self._handle_manual_verify(chat_id)
                        elif text.startswith("/check_payment") or text.startswith("/verify_"):
                            # v2.0: Robust ID extraction using regex
                            import re
                            match = re.search(r'(pl_[a-zA-Z0-9]+)', text)
                            link_id = match.group(1) if match else None
                            self._handle_check_payment(chat_id, link_id)
                        elif text == "/bulk":
                            self._handle_bulk_deals(chat_id)
                        elif text == "/upcoming":
                            self._handle_upcoming(chat_id)
                        elif text == "/status":
                            self._handle_status(chat_id)
                        elif text == "/admin":
                            self._send_raw(chat_id, "🔐 <b>Admin Dashboard (Interactive)</b>\nPlease use the dedicated Admin Bot for button-based controls.")
                        
                        elif str(chat_id) == os.getenv("TELEGRAM_ADMIN_CHAT_ID"):
                            if text.startswith("/grant"):
                                parts = text.split()
                                if len(parts) >= 3:
                                    target, days = parts[1], parts[2]
                                    self.db.add_working_days(target, int(days))
                                    self.db.toggle_user_status(target, 1)
                                    self._send_raw(chat_id, f"✅ User {target} granted {days} days.")
                            elif text == "/users":
                                stats = self.db.get_user_stats()
                                self._send_raw(chat_id, f"👥 Total: {stats[0]} | Active: {stats[1]}")

                    # 3. Callback Query Handling (Rule #24)
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        chat_id = str(cb["message"]["chat"]["id"])
                        msg_id = cb["message"]["message_id"]
                        data = cb.get("data", "")
                        
                        logger.info(f"Callback Received: {data} from {chat_id}")
                        
                        if data == "sub_menu":
                            self._handle_subscribe_menu(chat_id)
                        elif data == "view_billing":
                            self._handle_billing_history(chat_id)
                        
                        # Answer callback
                        requests.post(f"{self.base_url}/answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=5)

        except requests.exceptions.Timeout:
            # Expected during long polling, gracefully continue
            pass
        except Exception as e:
            logger.error(f"Failed to handle Telegram updates: {e}")

    def _handle_plan(self, chat_id, first_name):
        """v1.0: Precise expiry using TradingCalendar instead of guesswork."""
        user = self.db.get_user(chat_id)
        if not user:
            self._send_welcome(chat_id, first_name)
            return

        uid, name, uname, active, days = user
        name = self._clean_name(name)

        # v1.0: Accurate expiry — calendar walk
        try:
            from nse_monitor.trading_calendar import TradingCalendar
            expiry_dt = TradingCalendar.get_expiry_date(days)
            expiry_str = expiry_dt.strftime("%d %b %Y")
        except Exception:
            import pytz
            from datetime import timedelta
            tz = pytz.timezone("Asia/Kolkata")
            expiry_dt = datetime.now(tz) + timedelta(days=days + (days // 5) * 2)
            expiry_str = expiry_dt.strftime("%d %b %Y") + " (est.)"

        status_icon = "💎" if active else "🔘"
        status_text = "PREMIUM ACTIVE" if active else "TRIAL / EXPIRED"

        msg = (
            f"{status_icon} <b>INSTITUTIONAL ACCOUNT OVERVIEW</b>\n"
            f"────────────────────────\n"
            f"👤 <b>Client:</b> {name}\n"
            f"🆔 <b>Account ID:</b> <code>{chat_id}</code>\n\n"
            f"⏳ <b>Balance:</b> <code>{days} Market Days</code>\n"
            f"📅 <b>Expiry:</b> <code>{expiry_str}</code>\n"
            f"📡 <b>Service:</b> <b>{status_text}</b>\n"
            f"────────────────────────\n"
            f"💡 <i>Credits only deduct on NSE Trading Days. Public holidays and weekends are ALWAYS free.</i>"
        )

        keyboard = {
            "inline_keyboard": [
                [{"text": "💎 Extend / Upgrade Subscription", "callback_data": "sub_menu"}],
                [{"text": "📊 Detailed Billing Audit (Hisab)", "callback_data": "view_billing"}],
                [{"text": "🛠️ Institutional Support", "url": "https://wa.me/917985040858"}]
            ]
        }
        self._send_raw(chat_id, msg, keyboard)

    def _send_welcome(self, chat_id, first_name):
        """Unified Dashboard, Disclaimer and Onboarding (v10.2)."""
        user = self.db.get_user(chat_id)
        
        intro = (
            f"🏛️ <b>{BOT_NAME} Institutional Engine</b>\n\n"
            f"Welcome, {first_name}. You are connected to a high-precision NSE intelligence system. "
            f"Our engine scans institutional filings in real-time to identify high-impact market signals.\n"
        )
        
        disclaimer = (
            f"\n⚖️ <b>Regulatory Disclosure:</b>\n"
            f"<i>Non-SEBI Research Tool. Content is for educational and informational purposes only. "
            f"Trading involves substantial risk. Consultation with certified professionals is advised.</i>\n"
        )
        
        if user and user[4] > 0: # If has active credits, show Dashboard
            uid, name, uname, active, days = user
            name = self._clean_name(name)
            
            # Calculate Expiry
            tz = pytz.timezone("Asia/Kolkata")
            now = datetime.now(tz)
            offset_days = days + (days // 5) * 2
            expiry_str = (now + timedelta(days=offset_days)).strftime("%d %b %Y")
            
            dashboard = (
                f"🛰️ <b>DASHBOARD: {name}</b>\n"
                f"────────────────────────\n"
                f"⏳ <b>Credits:</b> <code>{days} Market Days</code>\n"
                f"📅 <b>Est. Expiry:</b> <code>{expiry_str}</code>\n"
                f"📡 <b>Status:</b> <b>PREMIUM ACTIVE 💎</b>\n"
                f"────────────────────────\n\n"
                f"{intro}"
                f"────────────────────────\n"
                f"🛠️ <b>Quick Shortcuts:</b>\n"
                f"• /plan - See detailed balance\n"
                f"• /bulk - Today's big deals\n"
                f"• /upcoming - NSE Corporate Calendar\n"
                f"• /support - WhatsApp Admin"
                f"{disclaimer}"
            )
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🛒 Subscribe / Top-up", "callback_data": "sub_menu"}],
                    [{"text": "🛠️ Contact Admin", "url": "https://wa.me/917985040858"}]
                ]
            }
            self._send_raw(chat_id, dashboard, keyboard)
            
        else: # New or Expired: Show Welcome + Instructions
            welcome_text = (
                f"{intro}\n"
                f"💎 <b>Current Status:</b> No Active Subscription\n"
                f"────────────────────────\n"
                f"{disclaimer}\n"
            )
            welcome_text += self._get_plan_menu()
            self._send_raw(chat_id, welcome_text)

    def _get_plan_menu(self):
        """Helper to return the structured plan menu text (v1.3.1)."""
        from nse_monitor.config import SUBSCRIPTION_PLANS
        
        msg = (
            "💎 <b>INSTITUTIONAL ACCESS PLANS</b>\n"
            "<i>Market-Day Billing (Zero loss on holidays)</i>\n"
            "────────────────────────\n"
        )
        
        # Order by price low to high
        sorted_keys = sorted(SUBSCRIPTION_PLANS.keys(), key=lambda x: int(x))
        for k in sorted_keys:
            plan = SUBSCRIPTION_PLANS[k]
            price = plan["amount"]
            days = plan["days"]
            label = "Working Days" if days > 2 else "Market Days"
            if days >= 336: label = "Days"
            
            msg += f"🔸 <b>Plan:</b> ₹{price} ({days} {label})\n"
            msg += f"👉 /sub_{price}\n\n"
        
        msg += "────────────────────────\n"
        msg += "💡 Select a plan above to generate a secure link."
        return msg

    def _handle_subscribe_menu(self, chat_id):
        """Displays available plans to the user."""
        self._send_raw(chat_id, self._get_plan_menu())

    def _send_expiry_reminder(self, chat_id):
        """Sends a nudge to expired users."""
        msg = (
            "⚠️ <b>SUBSCRIPTION EXPIRED</b>\n"
            "────────────────────────\n"
            "Your Market-Day credits have been exhausted. "
            "To continue receiving high-impact NSE signals and morning reports, please subscribe to a plan.\n\n"
        )
        msg += self._get_plan_menu()
        self._send_raw(chat_id, msg)

    def _handle_login(self, chat_id, text):
        parts = text.split()
        if len(parts) < 2:
            self._send_raw(chat_id, "❌ Usage: <code>/login <password></code>")
            return
            
        provided_password = parts[1]
        if provided_password == ADMIN_PASSWORD:
            self.admin_sessions[str(chat_id)] = time.time()
            self._send_raw(chat_id, "🔓 <b>Admin Authentication Successful.</b>\nAccess is granted for <b>5 minutes</b>. Use /logout to exit early.")
            logger.warning(f"ADMIN LOGIN: {chat_id}")
        else:
            self._send_raw(chat_id, "🚫 <b>Invalid Password.</b> Access Denied.")
            logger.error(f"FAILED LOGIN ATTEMPT: {chat_id}")

    def _handle_logout(self, chat_id):
        if str(chat_id) in self.admin_sessions:
            del self.admin_sessions[str(chat_id)]
            self._send_raw(chat_id, "🔒 <b>Logged Out.</b>\nYour admin session has been terminated.")
            logger.info(f"ADMIN LOGOUT: {chat_id}")
        else:
            self._send_raw(chat_id, "No active admin session found.")

        if not self.is_admin(chat_id):
            self._send_raw(chat_id, "🔒 <b>Session Expired or Unauthorized.</b>\nPlease use <code>/login <pass></code>")
            return
            
        total, active = self.db.get_user_stats() if self.db else (0, 0)
        status_text = (
            f"📊 <b>SYSTEM STATUS</b>\n"
            f"────────────────────────\n"
            f"✅ <b>Signal Engine:</b> ACTIVE\n"
            f"🧠 <b>AI Processor:</b> ONLINE\n"
            f"👥 <b>Total Users:</b> {total}\n"
            f"⚡ <b>Active Subs:</b> {active or 0}\n"
            f"────────────────────────\n"
            f"📍 <i>Server: Institutional v7.6</i>"
        )
        self._send_raw(chat_id, status_text)
        
    def _handle_users(self, chat_id):
        if not self.is_admin(chat_id): return
        users = self.db.get_all_users(limit=20)
        
        msg = "👥 <b>LATEST USERS (AUDIT)</b>\n"
        msg += "<i>Click ID to copy for /grant</i>\n"
        msg += "────────────────────────\n"
        for u in users:
            uid, name, uname, active, days = u
            name = self._clean_name(name)
            status = "✅" if active else "❌"
            # Format: [Status] Name | ID | Days
            msg += f"{status} {name or 'N/A'} (<code>{uid}</code>) | {days}d left\n"
        
        self._send_raw(chat_id, msg)

    def _handle_me(self, chat_id, first_name):
        """Shows the user their own information."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT is_active, working_days_left FROM users WHERE id = ?", (str(chat_id),))
        user = cursor.fetchone()
        
        active_status = "✅ ACTIVE" if user and user[0] else "❌ INACTIVE"
        days = user[1] if user else 0
        
        msg = (
            f"👤 <b>USER PROFILE</b>\n"
            f"────────────────────────\n"
            f"👋 <b>Name:</b> {first_name}\n"
            f"🆔 <b>My ID:</b> <code>{chat_id}</code>\n"
            f"💎 <b>Status:</b> {active_status}\n"
            f"⏳ <b>Market Days Left:</b> {days}\n"
            f"────────────────────────\n"
            f"💡 <i>Give this ID to Admin for manual support.</i>"
        )
        self._send_raw(chat_id, msg)

    def _handle_grant(self, admin_chat_id, text):
        """Manually grant subscription days to a user."""
        if not self.is_admin(admin_chat_id): return
        
        parts = text.split()
        if len(parts) < 3:
            self._send_raw(admin_chat_id, "⚠️ Usage: <code>/grant <chat_id> <days></code>")
            return
            
        target_id, days = parts[1], parts[2]
        try:
            days_int = int(days)
            self.db.add_working_days(target_id, days_int)
            self._send_raw(admin_chat_id, f"✅ <b>Granted {days_int} Market Days</b> to user <code>{target_id}</code>.")
            logger.warning(f"ADMIN GRANT: {days_int} days to {target_id} by {admin_chat_id}")
            
            # Notify the user
            self._send_raw(target_id, f"🎁 <b>Subscription Updated!</b>\nAdmin has manually credited your account with <b>{days_int} Market Days</b>. Enjoy premium signals!")
        except ValueError:
            self._send_raw(admin_chat_id, "❌ <i>Days</i> must be a number.")
        except Exception as e:
            logger.error(f"Manual grant failed: {e}")
            self._send_raw(admin_chat_id, f"❌ Error: {str(e)}")

    def _handle_toggle(self, admin_chat_id, text, active_val):
        if not self.is_admin(admin_chat_id): return
        parts = text.split()
        if len(parts) < 2:
            self._send_raw(admin_chat_id, f"⚠️ Usage: <code>/{ 'activate' if active_val else 'deactivate' } <chat_id></code>")
            return
        
        target_id = parts[1]
        self.db.toggle_user_status(target_id, active_val)
        status_label = "ACTIVATED" if active_val else "DEACTIVATED"
        self._send_raw(admin_chat_id, f"🎯 User <code>{target_id}</code> has been <b>{status_label}</b>.")
        logger.info(f"ADMIN {status_label}: {target_id} by {admin_chat_id}")

    def _handle_broadcast(self, chat_id, text):
        if not self.is_admin(chat_id): return
        parts = text.split(" ", 1)
        if len(parts) < 2:
            self._send_raw(chat_id, "⚠️ Usage: <code>/broadcast <message></code>")
            return
            
        message = parts[1]
        active_users = self.db.get_active_users()
        
        sent = 0
        for uid in active_users:
            try:
                self._send_raw(uid, f"📢 <b>ADMIN BROADCAST</b>\n────────────────────────\n{message}")
                sent += 1
                time.sleep(0.05)
            except: continue
        self._send_raw(chat_id, f"✅ <b>Broadcast Sent!</b>\nDelivered to {sent} active subscribers.")

    def _handle_bulk_deals(self, chat_id):
        """Fetches bulk deals and always replies (live or cached)."""
        self._send_raw(chat_id, "⏳ <b>Fetching today's bulk deals...</b>")
        try:
            if not self.nse_client:
                self._send_raw(chat_id, "❌ <b>NSE Client Error.</b>")
                return

            now = datetime.now(self.ist)
            date_str = now.strftime("%d-%m-%Y")
            hist_url = f"https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from={date_str}&to={date_str}"
            hist_referer = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
            data = self._run_async(self.nse_client.get_json(hist_url, referer=hist_referer))
            deals = data.get("data", []) if data else []

            if not deals:
                live_url = "https://www.nseindia.com/api/live-analysis-bulk-deal"
                live_referer = "https://www.nseindia.com/report-search/equities?id=all-daily-reports"
                live_data = self._run_async(
                    self.nse_client.get_json(live_url, referer=live_referer, warmup="https://www.nseindia.com/report-search/equities")
                )
                if live_data:
                    deals = live_data.get("data", [])

            if not deals:
                cached = []
                if self.db:
                    cached = [n for n in self.db.get_recent_news(hours=72) if n.get("source") == "NSE_BULK"][:8]
                if not cached:
                    self._send_raw(chat_id, "📊 <b>Bulk Deals</b>\n<i>No live trades reported and no recent cache found.</i>")
                    return
                msg = "📊 <b>BULK DEALS (Cached)</b>\n────────────────────────\n"
                for n in cached:
                    msg += f"• <b>{n.get('symbol','N/A')}</b> | {n.get('headline','N/A')[:90]}\n"
                msg += "\n⚖️ <i>Non-SEBI Educational Resource</i>"
                self._send_raw(chat_id, msg)
                return

            msg = "📊 <b>TODAY'S BULK DEALS</b>\n────────────────────────\n"
            for d in deals[:10]:
                if "BD_SYMBOL" in d:
                    qty = str(d.get("BD_QTY_TRD", "0")).replace(",", "")
                    icon = "🟢" if d.get("BD_BUY_SELL") == "BUY" else "🔴"
                    msg += f"{icon} <b>{d.get('BD_SYMBOL')}</b> | {d.get('BD_BUY_SELL')}\n"
                    msg += f"   Client: {d.get('BD_CLIENT_NAME')}\n"
                    msg += f"   Qty: {int(float(qty)):,} @ ₹{d.get('BD_TP_WATP')}\n\n"
                else:
                    qty = d.get("quantityTraded", 0)
                    price = d.get("tradePrice", 0)
                    bos = d.get("buySellFlag", "")
                    icon = "🟢" if bos == "BUY" else "🔴"
                    msg += f"{icon} <b>{d.get('symbol')}</b> | {bos}\n"
                    msg += f"   Client: {d.get('clientName')}\n"
                    msg += f"   Qty: {qty:,} @ ₹{price}\n\n"

            msg += "⚖️ <i>Non-SEBI Educational Resource</i>"
            self._send_raw(chat_id, msg)
        except Exception as e:
            logger.error(f"Bulk deals fetch error: {e}")
            self._send_raw(chat_id, "❌ <b>NSE data temporarily unavailable.</b>")

    def _handle_upcoming(self, chat_id):
        """Upcoming calendar placeholder."""
        self._send_raw(chat_id, "🗓️ <b>Corporate Calendar</b>\n<i>Coming soon.</i>")
        return

    # NOTE: _handle_subscribe_menu is defined at line ~310 (dynamic version). Duplicate removed.

    def _handle_plan_selection(self, chat_id, text, first_name):
        """Generates link for selected plan and saves for auto-verification in a separate thread."""
        plan_type = text.replace("/sub_", "")
        logger.info(f"Plan selection request: {plan_type} by {chat_id}")
        self._send_raw(chat_id, f"⌛ <b>Generating secure payment link for ₹{plan_type} plan...</b>")
        
        # Offload to thread to prevent UI hang on Razorpay API delays
        import threading
        thread = threading.Thread(
            target=self._generate_link_threaded, 
            args=(chat_id, plan_type, first_name),
            daemon=True
        )
        thread.start()

    def _generate_link_threaded(self, chat_id, plan_type, first_name):
        """Background thread worker for payment link creation."""
        try:
            link_data = self.payment_processor.create_payment_link(chat_id, plan_type, first_name)
            
            if link_data:
                # RULE #24: Save for background poller (Fixed args to match DB schema)
                if self.db:
                    self.db.save_payment_link(
                        link_id=link_data["id"],
                        chat_id=chat_id,
                        days=link_data["days"]
                    )
                
                msg = (
                    f"🔗 <b>Your Payment Link is Ready:</b>\n{link_data['short_url']}\n\n"
                    f"✅ Credits will be added automatically within 1-2 mins after payment.\n\n"
                    f"⚠️ <i>Please do not close the payment page until you see the success message.</i>"
                )
                self._send_raw(chat_id, msg)
            else:
                self._send_raw(chat_id, "❌ <b>Payment Service Busy.</b>\nPlease try generating the link again in a few minutes.")
                
        except Exception as e:
            logger.error(f"Threaded link generation failed: {e}", exc_info=True)
            self._send_raw(chat_id, "⚠️ <b>System Error.</b>\nOur payment partner is unreachable. Please contact support.")

    # v1.1: First send_signal removed. Keeping the polished v15.0 version below.

    def _handle_manual_verify(self, chat_id):
        """Triggered by the /verify command (Rule #24)."""
        pending = self.db.get_pending_payment_links()
        user_pending = [p for p in pending if str(p[1]) == str(chat_id)]
        
        if not user_pending:
            self._send_raw(chat_id, "❓ <b>No Pending Payments Found.</b>\nIf you just paid, please wait 2-3 minutes or contact support.")
            return
            
        # Check the latest one
        link_id = user_pending[-1][0]
        self._send_raw(chat_id, f"🔍 <b>Verifying Ref: <code>{link_id}</code>...</b>")
        self._handle_check_payment(chat_id, link_id)

    def _handle_check_payment(self, chat_id, link_id):
        """Internal helper to verify Razorpay status (Fraud-Proof)."""
        if not link_id:
            self._send_raw(chat_id, "❌ Invalid transaction reference.")
            return
            
        days_to_add = self.payment_processor.verify_payment_status(link_id)
        if days_to_add:
            # RULE #24: Credit Working Days
            self.db.add_working_days(chat_id, days_to_add)
            self.db.update_payment_link_status(link_id, 'processed') # Clean up
            
            msg = (
                f"🎉 <b>Success! {days_to_add} Market Days credited.</b>\n"
                f"────────────────────────\n"
                f"Your premium access is now <b>LIVE</b>. 🚀\n"
                f"Use /plan to see your new expiry date."
            )
            self._send_raw(chat_id, msg)
            logger.info(f"USER PAID (MANUAL VERIFY): {chat_id} | {days_to_add} days via {link_id}")
        else:
            self._send_raw(chat_id, "⏳ <b>Transaction Pending.</b>\nRazorpay hasn't confirmed this payment yet. Please try again in 5 minutes.")

    def is_admin(self, chat_id):
        # Session valid for 5 minutes (300 seconds)
        session_time = self.admin_sessions.get(str(chat_id), 0)
        return (time.time() - session_time) < 300

    def _send_raw(self, chat_id, text, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "protect_content": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        return self._execute_request("sendMessage", payload)

    def _repair_mojibake_text(self, value):
        """Best-effort fix for UTF-8 text that was decoded as Latin-1/CP1252."""
        if not isinstance(value, str) or not value:
            return value

        markers = ("Ã", "Â", "â", "ðŸ", "ï¸")
        repaired = value

        for _ in range(2):
            if not any(marker in repaired for marker in markers):
                break
            try:
                candidate = repaired.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if not candidate or candidate == repaired:
                break
            repaired = candidate

        return repaired

    def _sanitize_payload(self, payload):
        if isinstance(payload, str):
            return self._repair_mojibake_text(payload)
        if isinstance(payload, list):
            return [self._sanitize_payload(item) for item in payload]
        if isinstance(payload, dict):
            return {k: self._sanitize_payload(v) for k, v in payload.items()}
        return payload

    def send_admin_alert(self, text):
        """v1.3: Sends a critical system alert to the Administrator chat ID."""
        admin_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        if not admin_id: return
        
        payload = {
            "chat_id": admin_id,
            "text": f"🛠️ <b>{BOT_NAME} — SYSTEM ALERT</b>\n────────────────────────\n{text}",
            "parse_mode": "HTML"
        }
        return self._execute_request("sendMessage", payload)

    def _execute_request(self, method, payload, retries=3):
        """Internal helper with 429 Rate-Limit resilience (v1.3)."""
        url = f"{self.base_url}/{method}"
        payload = self._sanitize_payload(payload)
        for attempt in range(retries):
            try:
                r = requests.post(url, json=payload, timeout=15)
                if r.status_code == 429:
                    # RULE #24: Exponential Backoff for Rate Limits
                    retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                    logger.warning(f"⚠️ Telegram Rate Limit (429). Backing off for {retry_after}s...")
                    time.sleep(retry_after + 1)
                    continue
                
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"Telegram Request Failed ({method}): {e}")
                    return None
                time.sleep(1 * (attempt + 1))
        return None

    def _send_document(self, chat_id, file_path, caption="Reference Filing Document"):
        """Returns (success, failed_reason)."""
        if not file_path or not os.path.exists(file_path):
            return False, "file_missing"
        endpoint = f"{self.base_url}/sendDocument"
        try:
            with open(file_path, "rb") as f:
                files = {
                    "document": (
                        os.path.basename(file_path),
                        f,
                        "application/pdf",
                    )
                }
                data = {
                    "chat_id": str(chat_id),
                    "caption": caption,
                }
                resp = requests.post(endpoint, data=data, files=files, timeout=TELEGRAM_DOCUMENT_TIMEOUT_SEC)
                if resp.status_code == 200:
                    return True, None
                reason = f"http_{resp.status_code}:{resp.text[:300]}"
                logger.error("PDF delivery failed chat_id=%s reason=%s", chat_id, reason)
                return False, reason
        except Exception as exc:
            reason = f"exception:{type(exc).__name__}:{exc}"
            logger.error("PDF delivery failed chat_id=%s reason=%s", chat_id, reason)
            return False, reason

    def send_report(self, report_text):
        """Sends a structured pre-market report to active users."""
        if not self.token: return
        report_text = self._repair_mojibake_text(report_text)
        
        active_users = self.db.get_active_users() if self.db else self.chat_ids
        for chat_id in active_users:
            payload = {
                "chat_id": chat_id,
                "text": report_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "protect_content": True
            }
            try:
                requests.post(f"{self.base_url}/sendMessage", json=self._sanitize_payload(payload), timeout=20)
            except Exception as e:
                logger.error(f"Failed to send report to {chat_id}: {e}")
        logger.info(f"Broadcasted report to {len(active_users)} active users.")

    def send_signal(self, item, analysis, pdf_path=None):
        """v15.0: Enhanced Signal Dispatcher with Big Ticket Badges and Source Awareness."""
        if not self.token or not self.chat_ids: return False

        symbol = html.escape(str(analysis.get("symbol", "N/A")))
        trigger = html.escape(str(analysis.get("trigger", "N/A")))
        impact_score = analysis.get("impact_score", 0)
        sentiment = html.escape(str(analysis.get("sentiment", "Neutral")))
        is_big_ticket = analysis.get("is_big_ticket", False)
        source = item.get("source", "NSE").upper()
        
        url = item.get("url")
        if url and not url.startswith("http"):
            url = f"https://nsearchives.nseindia.com/corporate/{url}"

        # v15.0: Visual Polish
        header = f"🛰️ <b>[{source}] {symbol.upper()}</b>"
        if is_big_ticket:
            header = f"🔥 <b>BIG TICKET: [{source}] {symbol.upper()}</b>"

        message = (
            f"{header} | Signal Engine\n"
            f"────────────────────────\n"
            f"🎯 <b>TRIGGER:</b> {trigger}\n"
            f"📊 <b>IMPACT:</b> {impact_score}/10\n"
            f"🧠 <b>SENTIMENT:</b> {sentiment}\n"
            f"────────────────────────\n"
            f"👉 <a href='{url or '#'}'>Reference Filing</a>\n\n"
            f"⚖️ <i>Non-SEBI Educational Resource</i>"
        )

        success = False
        active_users = self.db.get_active_users() if self.db else self.chat_ids
        
        for chat_id in active_users:
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "protect_content": True
            }
            try:
                r = requests.post(f"{self.base_url}/sendMessage", json=self._sanitize_payload(payload), timeout=15)
                if r.status_code == 200: success = True
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
            
        if pdf_path and os.path.exists(pdf_path):
            file_size = os.path.getsize(pdf_path) / (1024 * 1024)
            if file_size < 5:
                pdf_caption = f"Filings for {symbol.upper()} | Conviction: {impact_score}/10"
                for chat_id in active_users:
                    ok, failed_reason = self._send_document(chat_id, pdf_path, caption=pdf_caption)
                    if not ok:
                        fallback_text = "PDF upload failed in this network; filing link attached if available."
                        if url:
                            fallback_text += f"\n{url}"
                        self._send_raw(chat_id, fallback_text)
                        logger.warning("PDF fallback sent chat_id=%s failed_reason=%s", chat_id, failed_reason)

        return success
    def _handle_history(self, chat_id):
        """Displays user's successful payment history (v12.0)."""
        history = self.db.get_user_payment_history(chat_id)
        if not history:
            msg = (
                "📜 <b>TRANSCRIPT HISTORY</b>\n"
                "────────────────────────\n"
                "<i>No successful transactions found for your ID.</i>\n\n"
                "💡 If you recently paid, use /verify to sync."
            )
            self._send_raw(chat_id, msg)
            return

        msg = "📜 <b>TRANSACTION HISTORY</b>\n────────────────────────\n"
        for link_id, days, date_str in history[:10]: # Last 10
            # Simplify date
            try:
                date_ts = datetime.fromisoformat(date_str).strftime("%d %b, %H:%M")
            except:
                date_ts = date_str
            
            msg += f"✅ <b>+{days} Days</b> | <code>{link_id[-8:]}</code>\n"
            msg += f"   📅 {date_ts}\n\n"
        
        msg += "────────────────────────\n"
        msg += "📈 <i>Thank you for choosing Market Pulse Professional.</i>"
        self._send_raw(chat_id, msg)

    def _handle_billing_history(self, chat_id):
        """Displays the 'Hisab' audit trail for the user (v2.0)."""
        logs = self.db.get_billing_logs(chat_id, limit=8)
        
        if not logs:
            msg = (
                "📝 <b>BILLING AUDIT LOGS</b>\n"
                "────────────────────────\n"
                "<i>No billing activity found in the current audit period.</i>\n\n"
                "💡 Credits are only deducted on active NSE trading days."
            )
            self._send_raw(chat_id, msg)
            return

        msg = "📝 <b>BILLING AUDIT LOGS</b>\n────────────────────────\n"
        for evt, amt, reason, bal, date_str in logs:
            icon = "➖" if evt == "DEBIT" else "➕"
            # Simplify date
            try:
                date_ts = datetime.fromisoformat(date_str).strftime("%d %b, %H:%M")
            except:
                date_ts = date_str
            
            msg += f"{icon} <b>{amt} Market Day(s)</b> | {reason}\n"
            msg += f"   📅 {date_ts} | Bal: {bal}\n\n"
            
        msg += "────────────────────────\n"
        msg += "⚖️ <i>Internal Ledger transparency verified.</i>"
        self._send_raw(chat_id, msg)

    def _handle_status(self, chat_id):
        """v1.0: Live System Diagnostic — tests AI, NSE, DB, and RAM in real-time."""
        self._send_raw(chat_id, "🔍 <b>Running system diagnostics...</b>")

        lines = []
        lines.append("📊 <b>MARKET PULSE — SYSTEM STATUS</b>")
        lines.append("────────────────────────")

        # 1. NSE Connectivity
        try:
            import requests as _req
            r = _req.get("https://www.nseindia.com", timeout=5)
            nse_ok = r.status_code == 200
        except Exception:
            nse_ok = False
        lines.append(f"📡 <b>NSE Server:</b> {'✅ Online' if nse_ok else '❌ Unreachable'}")

        # 2. Sarvam AI
        try:
            from nse_monitor.config import SARVAM_API_KEY
            ai_ok = bool(SARVAM_API_KEY and "placeholder" not in SARVAM_API_KEY)
        except Exception:
            ai_ok = False
        lines.append(f"🧠 <b>AI Engine (Sarvam):</b> {'✅ Key Loaded' if ai_ok else '❌ Key Missing'}")

        # 3. Database health
        try:
            cursor = self.db.conn.execute("PRAGMA integrity_check")
            db_status = cursor.fetchone()[0]
            db_ok = db_status == "ok"
            # Queue count
            q_cursor = self.db.conn.execute(
                "SELECT COUNT(*) FROM news_items WHERE processing_status = 0"
            )
            pending_count = q_cursor.fetchone()[0]
        except Exception:
            db_ok = False
            pending_count = "?"
        lines.append(f"🗄️ <b>Database:</b> {'✅ Healthy' if db_ok else '❌ Corrupted'}")
        lines.append(f"📥 <b>Queue Pending:</b> <code>{pending_count}</code> items")

        # 4. User stats
        try:
            total, active = self.db.get_user_stats()
        except Exception:
            total, active = "?", "?"
        lines.append(f"👥 <b>Users:</b> {total} total | <b>{active}</b> active")

        # 5. RAM usage
        try:
            import psutil
            mem = psutil.virtual_memory()
            ram_used = mem.used / (1024 ** 2)
            ram_total = mem.total / (1024 ** 2)
            ram_pct = mem.percent
            lines.append(
                f"💾 <b>RAM:</b> <code>{ram_used:.0f}MB / {ram_total:.0f}MB ({ram_pct}%)</code>"
            )
        except ImportError:
            lines.append("💾 <b>RAM:</b> <i>psutil not installed</i>")
        except Exception:
            lines.append("💾 <b>RAM:</b> <i>Unavailable</i>")

        # 6. Trading day info
        try:
            from nse_monitor.trading_calendar import TradingCalendar
            import pytz
            tz = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(tz)
            is_trading = TradingCalendar.is_trading_day(now_ist)
            holiday_name = TradingCalendar.get_holiday_name(now_ist)
            if is_trading:
                cal_status = "✅ Trading Day"
            elif holiday_name:
                cal_status = f"🏖️ NSE Holiday ({holiday_name})"
            elif now_ist.weekday() >= 5:
                cal_status = "😴 Weekend"
            else:
                cal_status = "❌ Non-Trading"
            lines.append(f"📅 <b>Today:</b> {cal_status}")
        except Exception:
            pass

        lines.append("────────────────────────")
        lines.append("<i>v1.0 Industrial Engine | Non-SEBI</i>")

        self._send_raw(chat_id, "\n".join(lines))
