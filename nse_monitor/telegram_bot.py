import logging
import requests
import time
import html
import os
import json
import pytz
from datetime import datetime, timedelta
from nse_monitor.config import BOT_NAME, ADMIN_PASSWORD
from nse_monitor.payment_processor import RazorpayProcessor

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, db=None):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = db
        self.payment_processor = RazorpayProcessor()
        self.chat_ids = [] # Use list for append/ordering
        self.dynamic_ids_file = "data/dynamic_chat_ids.json"
        self.admin_sessions = {} # chat_id: timestamp
        self.last_update_id = 0 # Track Telegram offsets
        self._load_dynamic_ids()
        self._sync_with_db()
        self.set_my_commands()

    def set_my_commands(self):
        """Sets the blue menu buttons in the Telegram UI (Rule #24)."""
        if not self.token: return
        commands = [
            {"command": "plan", "description": "💎 My Subscription & Expiry"},
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
        for chat_id in self.chat_ids:
            self.db.save_user(chat_id, "Sync_Legacy", "Legacy")

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
        """Registers the bot commands in the Telegram menu."""
        url = f"{self.base_url}/setMyCommands"
        commands = [
            {"command": "start", "description": "Activate Engine & Legal Disclaimer"},
            {"command": "subscribe", "description": "Get Premium Access (Razorpay Link)"},
            {"command": "me", "description": "Show My ID & Subscription Balance"}
        ]
        try:
            requests.post(url, json={"commands": commands}, timeout=10)
        except Exception as e:
            logger.error(f"Failed to register commands: {e}")

    def handle_updates(self):
        """Checks for new messages and handles commands."""
        if not self.token: return
        
        try:
            url = f"{self.base_url}/getUpdates"
            params = {"offset": self.last_update_id + 1, "timeout": 1}
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    self.last_update_id = update["update_id"]
                    if "message" in update:
                        chat_id = str(update["message"]["chat"]["id"])
                        text = update["message"].get("text", "").strip()
                        first_name = update["message"]["from"].get("first_name", "User")
                        
                        # 1. Registration Logic
                        if chat_id not in self.chat_ids:
                            username = update["message"]["from"].get("username", "Unknown")
                            is_new = self.db.save_user(chat_id, first_name, username) if self.db else False
                            self.chat_ids.add(chat_id)
                            
                            if is_new:
                                self._send_raw(chat_id, "🎁 <b>Welcome Offer Activated!</b>\nYou've been credited with <b>2 Free Market Days</b> as a first-time user. Signals start now!")
                                logger.info(f"New User Registered + Trial: {first_name} (@{username}) | ID: {chat_id}")
                            else:
                                username = update["message"]["from"].get("username", "Unknown")
                                self.db.sync_user(chat_id, first_name, username)
                                logger.info(f"Existing User Re-synced: {first_name} (@{username}) | ID: {chat_id}")

                        # 2. Command Router
                        if text == "/start":
                            self._send_welcome(chat_id, first_name)
                        elif text == "/plan" or text == "/me":
                            self._handle_plan(chat_id, first_name)
                        elif text == "/subscribe":
                            self._handle_subscribe_menu(chat_id)
                        elif text.startswith("/sub_"):
                            self._handle_plan_selection(chat_id, text, first_name)
                        elif text == "/support":
                            self._send_raw(chat_id, "🛠️ <b>Contact Support</b>\nClick the button below to message the owner on WhatsApp.", 
                                          {"inline_keyboard": [[{"text": "📲 Message on WhatsApp", "url": "https://wa.me/917985040858"}]]})
                        elif text == "/verify":
                            self._handle_manual_verify(chat_id)
                        elif text.startswith("/check_payment") or text.startswith("/verify_"):
                            # Handle both auto-links and manual verify
                            parts = text.split("_")
                            link_id = parts[1] if len(parts) > 1 else None
                            self._handle_check_payment(chat_id, link_id)
                        elif text == "/bulk":
                            self._handle_bulk_deals(chat_id)
                        elif text == "/upcoming":
                            self._handle_upcoming(chat_id)
                        elif text == "/admin":
                            self._send_raw(chat_id, "🔐 <b>Admin Dashboard (Interactive)</b>\nPlease use the dedicated Admin Bot for button-based controls.")
                        
                        # 👑 OWNER-ONLY FALLBACK COMMANDS (Rule #24)
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

        except Exception as e:
            logger.error(f"Failed to handle Telegram updates: {e}")

    def _handle_plan(self, chat_id, first_name):
        """Rich user plan and expiry tracking (v9.0)."""
        user = self.db.get_user(chat_id)
        if not user:
             self._send_welcome(chat_id, first_name)
             return

        uid, name, uname, active, days = user
        
        # Calculate Estimated Expiry (Simple offset for weekends)
        from datetime import datetime, timedelta
        tz = pytz.timezone("Asia/Kolkata")
        now = datetime.now(tz)
        
        # Estimate: Add ~40% for weekends if long duration
        offset_days = days + (days // 5) * 2
        expiry_dt = now + timedelta(days=offset_days)
        expiry_str = expiry_dt.strftime("%d %b %Y")
        
        status_icon = "💎" if active else "🆓"
        status_text = "PREMIUM ACTIVE" if active else "FREE/EXPIRED"
        
        msg = (
            f"{status_icon} <b>YOUR MARKET PULSE PLAN</b>\n"
            f"────────────────────────\n"
            f"👤 <b>User:</b> {name}\n"
            f"🆔 <b>ID:</b> <code>{chat_id}</code>\n\n"
            f"⏳ <b>Credits:</b> <code>{days} Market Days</code>\n"
            f"📅 <b>Est. Expiry:</b> <code>{expiry_str}</code>\n"
            f"📡 <b>Status:</b> <b>{status_text}</b>\n"
            f"────────────────────────\n"
            f"<i>(Note: Credits only debit on trading days)</i>"
        )
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "💎 Renew / Upgrade Plan", "callback_data": "sub_menu"}],
                [{"text": "🛠️ Contact Admin (WhatsApp)", "url": "https://wa.me/917985040858"}]
            ]
        }
        self._send_raw(chat_id, msg, keyboard)

    def _send_welcome(self, chat_id, first_name):
        welcome_text = (
            f"🚀 <b>{BOT_NAME} Online</b>\n\n"
            f"Hello {first_name}! I am your high-precision NSE intelligence engine.\n\n"
            f"<b>Core Capabilities:</b>\n"
            f"• Direct Institutional Corporate Filings\n"
            f"• Real-time high-impact signals (>7 Score)\n"
            f"• Bulk/Block Deal intelligence\n\n"
            f"⚖️ <b>SEBI DISCLAIMER:</b>\n"
            f"<i>This automated engine is for INFORMATIONAL & EDUCATIONAL purposes only. "
            f"Content does not constitute financial, legal, or investment advice. "
            f"We are NOT SEBI Registered advisors. Trading carries substantial risk; "
            f"please consult a certified professional before taking any action.</i>\n\n"
        )
        welcome_text += self._get_plan_menu()
        self._send_raw(chat_id, welcome_text)

    def _get_plan_menu(self):
        """Helper to return the structured plan menu text (Dynamic v8.2)."""
        from nse_monitor.config import SUBSCRIPTION_PLANS
        
        msg = (
            "💎 <b>PREMIUM PLANS (MARKET DAYS)</b>\n"
            "<i>(Subscription only debits on trading days)</i>\n"
            "────────────────────────\n"
        )
        
        # Order by price low to high
        sorted_keys = sorted(SUBSCRIPTION_PLANS.keys(), key=lambda x: int(x))
        for k in sorted_keys:
            plan = SUBSCRIPTION_PLANS[k]
            price = plan["amount"]
            days = plan["days"]
            label = "Working Days" if days > 2 else "Market Days"
            if days >= 336: label = "Year"
            
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
        # Placeholder for real DB query from BulkDealSource
        msg = "📊 <b>Latest Bulk Deal Intelligence</b>\n<i>Coming soon: Streamed from NSE x Moneycontrol</i>"
        self._send_raw(chat_id, msg)

    def _handle_upcoming(self, chat_id):
        msg = "🗓️ <b>Upcoming High-Impact Triggers</b>\n<i>Monitoring: Mergers, Splits & Dividend Record Dates.</i>"
        self._send_raw(chat_id, msg)

    def _handle_subscribe_menu(self, chat_id):
        """Displays available plans to the user."""
        msg = (
            "💎 <b>PREMIUM PLANS (MARKET DAYS)</b>\n"
            "<i>(Subscription only debits on trading days)</i>\n"
            "────────────────────────\n"
            "🔸 <b>Starter:</b> ₹99 (2 Market Days)\n"
            "👉 /sub_99\n\n"
            "🔹 <b>Growth:</b> ₹499 (7 Working Days)\n"
            "👉 /sub_499\n\n"
            "🚀 <b>Pro:</b> ₹999 (28 Working Days)\n"
            "👉 /sub_999\n\n"
            "🏆 <b>Institutional:</b> ₹5999 (336 Days)\n"
            "👉 /sub_5999\n"
            "────────────────────────\n"
            "💡 Select a plan above to generate a secure link."
        )
        self._send_raw(chat_id, msg)

    def _handle_plan_selection(self, chat_id, text, first_name):
        """Generates link for selected plan and saves for auto-verification."""
        plan_type = text.replace("/sub_", "")
        self._send_raw(chat_id, f"⌛ <b>Generating link for ₹{plan_type} plan...</b>")
        link_data = self.payment_processor.create_payment_link(chat_id, plan_type, first_name)
        if link_data:
            # RULE #24: Save for background poller
            if self.db:
                self.db.save_payment_link(link_data['id'], chat_id, link_data['days'])
                
            msg = (
                f"🔗 <b>Your Payment Link is Ready:</b>\n{link_data['short_url']}\n\n"
                f"⚡ <b>Auto-Activation:</b> Your premium access will be activated <b>automatically</b> "
                f"within 1-2 minutes of payment. No further action needed!"
            )
            self._send_raw(chat_id, msg)
        else:
            self._send_raw(chat_id, "❌ Error generating link. Please try later.")

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
            
        try:
            requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Raw send failed: {e}")

    def send_report(self, report_text):
        """Sends a structured pre-market report to active users."""
        if not self.token: return
        
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
                requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=20)
            except Exception as e:
                logger.error(f"Failed to send report to {chat_id}: {e}")
        logger.info(f"Broadcasted report to {len(active_users)} active users.")

    def send_alert(self, data):
        """Sends a high-precision market alert with SEBI disclaimer."""
        if not self.token or not self.chat_ids: return

        report = data.get("ai_report") or {}
        symbol = html.escape(str(data.get("symbol", "N/A")))
        trigger = html.escape(str(data.get("trigger", "N/A")))
        
        impact_score = data.get("impact_score", "N/A")
        sentiment = html.escape(str(data.get("sentiment", "Neutral")))
        url = data.get("url")
        if url and not url.startswith("http"):
            url = f"https://nsearchives.nseindia.com/corporate/{url}"

        # RULE #21: Precision Format
        message = (
            f"🛰️ <b>{symbol.upper()}</b> | Signal Engine\n"
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
                r = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
                if r.status_code == 200: success = True
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
            
        return success
