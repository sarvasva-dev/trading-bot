import logging
import aiohttp
import asyncio
import html
import os
import json
import pytz
import time
import bcrypt
from collections import defaultdict
from datetime import datetime, timedelta
from nse_monitor.config import BOT_NAME, ADMIN_SESSION_TIMEOUT_MINUTES, TELEGRAM_DOCUMENT_TIMEOUT_SEC, HEADERS, TELEGRAM_ADMIN_CHAT_ID, TELEGRAM_ADMIN_CHAT_IDS
from nse_monitor.payment_processor import RazorpayProcessor

logger = logging.getLogger(__name__)
# v2.0: Brute-force and Spam Protection tracking
user_command_times = defaultdict(list)
failed_logins = defaultdict(lambda: {'count': 0, 'locked_until': 0})

def rate_limit(max_calls=5, period=60):
    """Decorator to limit command frequency per chat_id."""
    def decorator(func):
        async def wrapper(self, chat_id, *args, **kwargs):
            now = time.time()
            # Clean old entries
            user_command_times[chat_id] = [t for t in user_command_times[chat_id] if now - t < period]
            
            if len(user_command_times[chat_id]) >= max_calls:
                await self._send_raw(chat_id, "⏳ <b>Too many requests.</b> Please wait a minute.")
                return
                
            user_command_times[chat_id].append(now)
            return await func(self, chat_id, *args, **kwargs)
        return wrapper
    return decorator

class TelegramBot:
    def __init__(self, db=None, nse_client=None):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = db
        self.nse_client = nse_client
        self.payment_processor = RazorpayProcessor()
        self.admin_sessions = {} # chat_id: timestamp
        self.last_update_id = 0 # Track Telegram offsets
        self.ist = pytz.timezone("Asia/Kolkata")
        self.session = None # Async session, will be created on demand
        self._sync_task = None
        self.broadcast_semaphore = asyncio.Semaphore(30) # v5.2: Parallel dispatch cap
        self._initialized = False

    async def ensure_session(self):
        """Ensures an aiohttp session is active for the bot."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def initialize(self):
        """Rule #24: Boot sequence for the async engine."""
        if self._initialized:
            return
        if not self.token:
            logger.error("Telegram Bot: TOKEN MISSING!")
            return
        await self.ensure_session()
        await self._sync_telegram_offset()
        await self._clear_webhook()
        await self.set_my_commands()
        self._initialized = True
        logger.info("Telegram Bot: Asynchronous Initialization complete.")

    async def _sync_telegram_offset(self):
        """Rule #24: Fetches the latest update_id from Telegram on boot to skip stale messages."""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {"limit": 1, "offset": -1}
            async with self.session.get(url, params=params, timeout=5) as r:
                data = await r.json()
                if data.get("ok") and data.get("result"):
                    self.last_update_id = data["result"][0]["update_id"]
                    logger.info(f"Telegram Bot: Boot sync complete. Offset set to {self.last_update_id}.")
        except Exception as e:
            logger.warning(f"Telegram Bot: Failed to sync offset on boot: {e}")

    async def _clear_webhook(self):
        """Ensure getUpdates polling is not blocked by an active webhook."""
        try:
            url = f"{self.base_url}/deleteWebhook"
            async with self.session.post(url, json={"drop_pending_updates": False}, timeout=8) as r:
                await r.json()
            logger.info("Telegram Bot: Webhook cleared for long-polling mode.")
        except Exception as e:
            logger.warning(f"Telegram Bot: deleteWebhook failed: {e}")

    async def set_my_commands(self):
        """Sets the unified blue menu buttons in the Telegram UI."""
        commands = [
            {"command": "start", "description": "🚀 Activate Engine & Menu"},
            {"command": "plan", "description": "💎 My Subscription & Expiry"},
            {"command": "myref", "description": "🎁 Refer & Earn Rewards"},
            {"command": "refstats", "description": "📈 Referral Stats & Wallet"},
            {"command": "hisab", "description": "📝 View Billing Logs (Hisab)"},
            {"command": "subscribe", "description": "🛒 Recharge / Upgrade"},
            {"command": "support", "description": "🛠️ Contact Admin (WhatsApp)"},
            {"command": "signals", "description": "📡 Last 10 Signals"}
        ]
        url = f"{self.base_url}/setMyCommands"
        try:
            async with self.session.post(url, json={"commands": commands}, timeout=5) as r:
                await r.json()
            logger.info("Telegram Command Menu (Blue Button) updated.")
        except Exception as e:
            logger.error(f"Failed to set commands: {e}")

    async def close(self):
        """Closes the bot session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _clean_name(self, name):
        if not name or name in ("Sync_Legacy", "Legacy", "manual_entry", "Unknown"):
            return "User"
        return name

    async def _save_dynamic_ids(self, chat_id=None, first_name=None, username=None):
        """Saves a new user to DB directly (v7.0: Removed JSON redundancy)."""
        if chat_id and self.db:
            self.db.save_user(chat_id, first_name, username)

    async def handle_updates_loop(self):
        """Continuously checks for new messages and handles commands (Async Loop)."""
        await self.initialize()
        
        while True:
            url = f"{self.base_url}/getUpdates"
            params = {"offset": self.last_update_id + 1, "timeout": 20}
            
            try:
                async with self.session.get(url, params=params, timeout=25) as r:
                    if r.status != 200:
                        logger.error(f"Telegram Bot error: {r.status}")
                        await asyncio.sleep(5)
                        continue
                    data = await r.json()
                
                if data.get("ok") and data.get("result"):
                    for update in data["result"]:
                        self.last_update_id = update["update_id"]
                        if "message" in update:
                            msg = update["message"]
                            chat_id = str(msg["chat"]["id"])
                            text = msg.get("text", "").strip()
                            first_name = msg["from"].get("first_name", "User")
                            username = msg["from"].get("username", "Unknown")
                            
                            # Process User
                            is_new = False
                            referral_code_from_start = None
                            if self.db:
                                user = self.db.get_user(chat_id)
                                if not user:
                                    source_tag = "direct"
                                    if text.startswith("/start "):
                                        param = text.split(maxsplit=1)[1].strip()
                                        # Parse referral deep-link: /start ref_<code>
                                        if param.startswith("ref_"):
                                            referral_code_from_start = param[4:]  # strip "ref_"
                                            source_tag = referral_code_from_start
                                        else:
                                            source_tag = param
                                    is_new = self.db.save_user(chat_id, first_name, username, source=source_tag)
                                else:
                                    self.db.sync_user(chat_id, first_name, username)

                            if is_new:
                                trial_enabled = self.db.is_free_trial_enabled()
                                trial_days = 0
                                ref_code = referral_code_from_start

                                if ref_code:
                                    referrer_uid = self.db.get_user_id_by_referral_code(ref_code)
                                    # Block self-referral
                                    if referrer_uid and str(referrer_uid) != str(chat_id):
                                        self.db.set_referral_attribution(chat_id, ref_code, referrer_uid)
                                        self.db.save_referral_event(referrer_uid, chat_id, ref_code, "signup")
                                        if trial_enabled:
                                            trial_days = self.db.get_referral_trial_days()
                                            self.db.save_referral_event(referrer_uid, chat_id, ref_code, "trial_started", amount=trial_days)
                                        else:
                                            self.db.save_referral_event(referrer_uid, chat_id, ref_code, "trial_skipped")
                                        await self._send_raw(referrer_uid, "🎁 <b>New Referral!</b> Someone joined using your link. You'll earn rewards when they subscribe.")
                                    elif referrer_uid and str(referrer_uid) == str(chat_id):
                                        self.db.save_referral_event(chat_id, chat_id, ref_code, "invalid_referral", metadata={"reason": "self_referral"})
                                    # else: unknown code — ignore silently
                                else:
                                    if trial_enabled:
                                        trial_days = self.db.get_direct_trial_days()

                                if trial_days > 0:
                                    self.db.add_working_days(chat_id, trial_days)
                                    self.db.toggle_user_status(chat_id, 1)
                                    await self._send_raw(chat_id, "🤝 <b>Professional Onboarding Complete.</b>\n"
                                                          "⚡ <b>Follow the Beat of Big Money News.</b>\n"
                                                          f"As a new user, you've been granted <b>{trial_days} Free Market-Days</b>.")
                                else:
                                    await self._send_raw(chat_id, "🤝 <b>Professional Onboarding Complete.</b>\n"
                                                          "Subscribe to a plan to start receiving institutional signals.")

                            # Ensure referral code exists for every user
                            self.db.get_referral_code(chat_id)

                            # Command Router
                            if text.startswith("/start"):
                                await self._send_welcome(chat_id, first_name)
                            elif text in ("/plan", "/me"):
                                await self._handle_plan(chat_id, first_name)
                            elif text.startswith("/myref") or text.startswith("/refstats") or text == "/refer":
                                await self._handle_myref(chat_id)
                            elif text == "/hisab" or text == "/billing":
                                await self._handle_billing_history(chat_id)
                            elif text.startswith("/sub_"):
                                await self._handle_plan_selection(chat_id, text, first_name)
                            elif text == "/support":
                                await self._send_raw(chat_id, "🛠️ <b>Contact Support</b>\nClick the button below to message the owner on WhatsApp.",
                                              {"inline_keyboard": [[{"text": "📲 Message on WhatsApp", "url": "https://wa.me/917985040858"}]]})
                            elif text == "/verify":
                                await self._handle_manual_verify(chat_id)
                            elif text.startswith("/check_payment") or text.startswith("/verify_"):
                                import re
                                match = re.search(r'(pl_[a-zA-Z0-9]+)', text)
                                link_id = match.group(1) if match else None
                                await self._handle_check_payment(chat_id, link_id)
                            elif text == "/status":
                                await self._handle_status(chat_id)
                            elif text == "/signals":
                                await self._handle_signals(chat_id)
                            elif text.startswith("/login"):
                                await self._handle_login(chat_id, text, msg["message_id"])
                            elif text == "/admin":
                                await self._send_raw(chat_id, "🔐 <b>Admin Dashboard (Interactive)</b>\nPlease use the dedicated Admin Bot.")
                            
                            elif str(chat_id) == os.getenv("TELEGRAM_ADMIN_CHAT_ID"):
                                if text.startswith("/grant"):
                                    parts = text.split()
                                    if len(parts) >= 3:
                                        target, days_str = parts[1], parts[2]
                                        try:
                                            days = int(days_str)
                                            if not (1 <= days <= 365):
                                                await self._send_raw(chat_id, "❌ <b>Error:</b> Range must be 1-365 days.")
                                            else:
                                                self.db.add_working_days(target, days)
                                                self.db.toggle_user_status(target, 1)
                                                await self._send_raw(chat_id, f"✅ User {target} granted {days} days.")
                                        except ValueError:
                                            await self._send_raw(chat_id, "❌ <b>Error:</b> Days must be a number.")
                                elif text == "/users":
                                    stats = self.db.get_user_stats()
                                    await self._send_raw(chat_id, f"👥 Total: {stats[0]} | Active: {stats[1]}")

                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            chat_id = str(cb["message"]["chat"]["id"])
                            data_cb = cb.get("data", "")
                            
                            if data_cb == "sub_menu":
                                await self._handle_subscribe_menu(chat_id)
                            elif data_cb == "view_billing":
                                await self._handle_billing_history(chat_id)
                            
                            await self._execute_request("answerCallbackQuery", {"callback_query_id": cb_id})

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Failed to handle Telegram updates: {e}", exc_info=True)
                await asyncio.sleep(5)


    @rate_limit(max_calls=10, period=60)
    async def _handle_plan(self, chat_id, first_name):
        """v1.0: Precise expiry using TradingCalendar instead of guesswork."""
        user = self.db.get_user(chat_id)
        if not user:
            await self._send_welcome(chat_id, first_name)
            return

        uid, name, uname, active, days = user
        name = self._clean_name(name)

        try:
            from nse_monitor.trading_calendar import TradingCalendar
            expiry_dt = TradingCalendar.get_expiry_date(days)
            expiry_str = expiry_dt.strftime("%d %b %Y")
        except Exception:
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
        await self._send_raw(chat_id, msg, keyboard)

    @rate_limit(max_calls=5, period=60)
    async def _handle_signals(self, chat_id):
        """FR-01: View last 10 dispatched signals."""
        user = self.db.get_user(chat_id)
        if not user or user[3] == 0:
            await self._send_raw(chat_id, "❌ <b>Premium Feature</b>\nThis command is only available to active subscribers.")
            return

        signals = self.db.get_last_signals(10)
        if not signals:
            await self._send_raw(chat_id, "📡 <b>No Recent Signals</b>\nThe engine hasn't dispatched any alerts recently.")
            return

        msg = "📡 <b>LAST 10 MARKET SIGNALS</b>\n────────────────────────\n"
        for idx, s in enumerate(signals, 1):
            time_str = s['dispatch_time'].split('.')[0] if s['dispatch_time'] else 'N/A'
            score_icon = "🔥" if s['score'] >= 8 else "⚡"
            
            # Format headline summary (truncate if too long)
            headline = s['headline'] or 'No Headline'
            if len(headline) > 40:
                headline = headline[:37] + "..."
                
            msg += (
                f"<b>{idx}. #{s['symbol']}</b> | Score: {s['score']}/10 {score_icon}\n"
                f"   🕒 <i>{time_str}</i>\n"
                f"   📝 <i>{headline}</i>\n"
            )
            if s['url']:
                msg += f"   🔗 <a href='{s['url']}'>View Document</a>\n"
            msg += "────────────────────────\n"
            
        await self._send_raw(chat_id, msg, disable_web_preview=True)

    async def _handle_myref(self, chat_id):
        """Show user's personal referral link and stats."""
        user = self.db.get_user(chat_id)
        if not user:
            await self._send_raw(chat_id, "❌ Please /start first.")
            return
        
        # Get referral code
        ref_code = self.db.get_referral_code(str(chat_id))
        stats = self.db.get_referral_stats(str(chat_id))
        
        # Get bot username
        bot_info = await self._execute_request("getMe", {})
        bot_username = bot_info["result"]["username"] if bot_info and "result" in bot_info else "BulkBeatTV_Bot"
        
        referral_link = f"https://t.me/{bot_username}?start=ref_{ref_code}"
        
        msg = (
            f"👥 <b>Your Referral Link</b>\n"
            f"────────────────────────\n"
            f"<code>{referral_link}</code>\n\n"
            f"📊 <b>Your Stats:</b>\n"
            f"  👤 Referred: {stats['joins']}\n"
            f"  ✅ Converted: {stats['conversions']}\n"
            f"  💰 Reward Balance: ₹{stats['reward_balance']}\n\n"
            f"👉 <a href='{referral_link}'>Share This Link</a> with friends!"
        )
        await self._send_raw(chat_id, msg)

    async def _send_welcome(self, chat_id, first_name):
        """Unified Dashboard, Disclaimer and Onboarding (v10.2)."""
        user = self.db.get_user(chat_id)
        
        intro = (
            f"🏛️ <b>{BOT_NAME} Institutional Engine</b>\n"
            f"<i>Follow the Beat of Big Money News with Smart Money</i>\n\n"
            f"Welcome, {first_name}. You are connected to a high-precision NSE intelligence system.\n\n"
            f"⚡ <b>Market Hours:</b> Live high-impact alerts dispatched instantly.\n"
            f"🌅 <b>After-Market:</b> Off-hour news is consolidated and dispatched at 8:30 AM IST next trading day.\n"
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
                f"• /support - WhatsApp Admin"
                f"{disclaimer}"
            )
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🛒 Subscribe / Top-up", "callback_data": "sub_menu"}],
                    [{"text": "🛠️ Contact Admin", "url": "https://wa.me/917985040858"}]
                ]
            }
            await self._send_raw(chat_id, dashboard, keyboard)
            
        else: # New or Expired: Show Welcome + Instructions
            welcome_text = (
                f"{intro}\n"
                f"💎 <b>Current Status:</b> No Active Subscription\n"
                f"────────────────────────\n"
                f"{disclaimer}\n"
            )
            welcome_text += self._get_plan_menu()
            await self._send_raw(chat_id, welcome_text)

    def _get_plan_menu(self):
        """Helper to return the structured plan menu text (v1.3.1)."""
        from nse_monitor.config import SUBSCRIPTION_PLANS
        
        msg = (
            "💎 <b>INSTITUTIONAL ACCESS PLANS</b>\n"
            "<i>Market-Day Billing (Zero loss on holidays)</i>\n"
            "────────────────────────\n"
        )
        
        sorted_keys = sorted(SUBSCRIPTION_PLANS.keys(), key=lambda x: int(x))
        for k in sorted_keys:
            plan = SUBSCRIPTION_PLANS[k]
            price = plan["amount"]
            days = plan["days"]
            label = "Working Days" if days > 2 else "Market Days"
            if days >= 336: label = "Annual"
            
            msg += f"🔸 <b>Plan:</b> ₹{price} ({days} {label})\n"
            msg += f"👉 /sub_{price}\n\n"
        
        msg += "────────────────────────\n"
        msg += "💡 Select a plan above to generate a secure payment link."
        return msg

    @rate_limit(max_calls=5, period=60)
    async def _handle_subscribe_menu(self, chat_id):
        """Displays available plans to the user."""
        await self._send_raw(chat_id, self._get_plan_menu())

    async def _send_expiry_reminder(self, chat_id):
        """Sends a nudge to expired users."""
        msg = (
            "⚠️ <b>SUBSCRIPTION EXPIRED</b>\n"
            "────────────────────────\n"
            "Your Market-Day credits have been exhausted. "
            "To continue receiving high-impact NSE signals, please subscribe.\n\n"
        )
        msg += self._get_plan_menu()
        await self._send_raw(chat_id, msg)

    @rate_limit(max_calls=3, period=60) # Strict rate limit for login attempts
    async def _handle_login(self, chat_id, text, message_id):
        from nse_monitor.config import ADMIN_PASSWORD_HASH
        
        # RULE: Delete the message immediately to prevent plaintext in history.
        await self._execute_request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        
        now = time.time()
        lock_info = failed_logins[str(chat_id)]
        if lock_info['locked_until'] > now:
            wait_sec = int(lock_info['locked_until'] - now)
            await self._send_raw(chat_id, f"🔒 <b>Security Lockout:</b> Too many failed attempts. Try again in {wait_sec} seconds.")
            return

        parts = text.split()
        if len(parts) < 2:
            await self._send_raw(chat_id, "❌ Usage: <code>/login <password></code>")
            return
            
        provided_password = parts[1]
        
        # v2.0: Secure Bcrypt Verification
        if not ADMIN_PASSWORD_HASH:
            await self._send_raw(chat_id, "⚠️ <b>System Error:</b> ADMIN_PASSWORD_HASH not configured in environment.")
            return

        try:
            is_valid = bcrypt.checkpw(provided_password.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8'))
        except Exception as e:
            logger.error(f"Bcrypt verification error: {e}")
            is_valid = False

        if is_valid:
            failed_logins[str(chat_id)] = {'count': 0, 'locked_until': 0} # Reset on success
            self.admin_sessions[str(chat_id)] = time.time()
            await self._send_raw(chat_id, "🔓 <b>Admin Authentication Successful.</b> Session active for 60 minutes.")
        else:
            failed_logins[str(chat_id)]['count'] += 1
            if failed_logins[str(chat_id)]['count'] >= 3:
                failed_logins[str(chat_id)]['locked_until'] = now + 900 # 15 min lock
                await self._send_raw(chat_id, "🚨 <b>3 Failures Reached.</b> 15-minute security lockout initiated.")
            else:
                remaining = 3 - failed_logins[str(chat_id)]['count']
                await self._send_raw(chat_id, f"🚫 <b>Invalid Password.</b> {remaining} attempts remaining.")

    async def _handle_logout(self, chat_id):
        if str(chat_id) in self.admin_sessions:
            del self.admin_sessions[str(chat_id)]
            await self._send_raw(chat_id, "🔒 <b>Logged Out.</b>")

    @rate_limit(max_calls=10, period=60)
    async def _handle_status(self, chat_id):
        """v1.0: Live System Diagnostic — tests AI, NSE, DB, and RAM in real-time."""
        if not self.is_admin(chat_id): return
        
        await self._send_raw(chat_id, "🔍 <b>Running system diagnostics...</b>")
        lines = ["📊 <b>BULKBEAT TV — SYSTEM STATUS</b>", "────────────────────────"]

        # 1. NSE Connectivity (Using actual BOT session)
        try:
            async with self.session.get("https://www.nseindia.com", timeout=5) as r:
                nse_ok = r.status == 200
        except Exception: nse_ok = False
        lines.append(f"📡 <b>NSE Server:</b> {'✅ Online' if nse_ok else '❌ Unreachable'}")

        # 2. Sarvam AI
        try:
            from nse_monitor.config import SARVAM_API_KEY
            ai_ok = bool(SARVAM_API_KEY and "placeholder" not in SARVAM_API_KEY)
        except Exception: ai_ok = False
        lines.append(f"🧠 <b>AI Engine (Sarvam):</b> {'✅ Key Loaded' if ai_ok else '❌ Key Missing'}")

        # 3. Database health
        try:
            pending_count = self.db.get_pending_news_count() if self.db else "?"
            lines.append(f"🗄️ <b>Database:</b> ✅ Healthy")
            lines.append(f"📥 <b>Queue Pending:</b> <code>{pending_count}</code> items")
        except Exception: lines.append(f"🗄️ <b>Database:</b> ❌ Status Unknown")

        # 4. User stats
        try:
            total, active = self.db.get_user_stats()
            lines.append(f"👥 <b>Users:</b> {total} total | <b>{active}</b> active")
        except: pass

        lines.append("────────────────────────")
        lines.append("<i>v1.0 Industrial Engine | Non-SEBI</i>")
        await self._send_raw(chat_id, "\n".join(lines))

    @rate_limit(max_calls=5, period=60)
    async def _handle_plan_selection(self, chat_id, text, first_name):
        """Generates link for selected plan and saves for auto-verification."""
        plan_type = text.replace("/sub_", "")
        try:
            amount = int(plan_type)
        except: return

        # v8.0: Apply admin-controlled one-time percent discount
        from nse_monitor.config import ENABLE_REFERRAL_DISCOUNT_WALLET
        final_amount = amount
        discount_percent = 0
        discount_applied = 0
        
        if ENABLE_REFERRAL_DISCOUNT_WALLET:
            discount_percent = self.db.get_user_discount_percent(chat_id)
            if discount_percent > 0 and amount > 1:
                discount_applied = min((amount * discount_percent) // 100, amount - 1)
                final_amount = amount - discount_applied
                
        nudge = f" ({discount_percent}% OFF, Rs.{discount_applied} discount applied!)" if discount_applied > 0 else ""
        await self._send_raw(chat_id, f"⌛ <b>Generating secure payment link for Rs.{final_amount}...</b>{nudge}")
        
        try:
            loop = asyncio.get_running_loop()
            from nse_monitor.config import SUBSCRIPTION_PLANS
            plan_meta = SUBSCRIPTION_PLANS.get(str(amount), {})
            days = plan_meta.get("days", 0)
            label = plan_meta.get("label", "Subscription")
            # Pass days+label so Razorpay notes are correct even when amount is discounted
            link_data = await loop.run_in_executor(
                None,
                lambda: self.payment_processor.create_payment_link(chat_id, str(final_amount), first_name, days=days, label=label)
            )

            if link_data:
                if self.db:
                    self.db.save_payment_link(
                        link_id=link_data["id"],
                        chat_id=chat_id,
                        days=days,
                        plan_amount=amount,
                        payable_amount=final_amount,
                        discount_percent=discount_percent,
                        discount_rupees=discount_applied,
                    )

                msg = f"🔗 <b>Link Ready:</b>\n{link_data['short_url']}\n\n✅ Auto-credits after payment."
                await self._send_raw(chat_id, msg)
        except Exception as e:
            logger.error(f"Link generation failed: {e}")
            await self._send_raw(chat_id, "⚠️ System Error. Please contact support.")

    @rate_limit(max_calls=5, period=60)
    async def _handle_manual_verify(self, chat_id):
        pending = self.db.get_pending_payment_links()
        user_pending = [p for p in pending if str(p[1]) == str(chat_id)]
        if not user_pending:
            await self._send_raw(chat_id, "❓ No Pending Payments Found.")
            return
        link_id = user_pending[-1][0]
        await self._handle_check_payment(chat_id, link_id)

    @rate_limit(max_calls=10, period=60)
    async def _handle_check_payment(self, chat_id, link_id):
        if not link_id: return
        loop = asyncio.get_running_loop()
        days_to_add = await loop.run_in_executor(None, lambda: self.payment_processor.verify_payment_status(link_id))
        if days_to_add:
            meta = self.db.get_payment_link_meta(link_id)
            self.db.add_working_days(chat_id, days_to_add)
            self.db.update_payment_link_status(link_id, 'processed')
            
            # v8.0: Credit Referral Reward
            # Reverse-lookup plan amount from days using SUBSCRIPTION_PLANS
            from nse_monitor.config import SUBSCRIPTION_PLANS
            plan_amount = next(
                (int(k) for k, p in SUBSCRIPTION_PLANS.items() if p["days"] == days_to_add), 0
            )
            payable_amount = int(meta.get("payable_amount") or 0) or plan_amount
            
            if payable_amount > 0:
                self.db.record_first_payment(chat_id, payable_amount, link_id)
                self.db.credit_referral_reward_on_conversion(chat_id, payable_amount, link_id)

            if int(meta.get("discount_percent") or 0) > 0:
                self.db.clear_user_discount_percent(chat_id)
                
            await self._send_raw(chat_id, f"🎉 Success! {days_to_add} Market Days credited.")
        else:
            await self._send_raw(chat_id, "⏳ Transaction Pending. Try again in 5 mins.")

    def is_admin(self, chat_id):
        cid = str(chat_id)
        # 1. Owner bypass (checks both single ID and list)
        if cid == TELEGRAM_ADMIN_CHAT_ID or cid in TELEGRAM_ADMIN_CHAT_IDS:
            return True
        # 2. In-memory session check (ephemeral)
        session_time = self.admin_sessions.get(cid, 0)
        return (time.time() - session_time) < (ADMIN_SESSION_TIMEOUT_MINUTES * 60)

    async def _send_raw(self, chat_id, text, reply_markup=None, disable_web_page_preview=False):
        # v2.5: Changed protect_content to False to allow screenshots/forwarding
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "protect_content": False}
        if reply_markup: payload["reply_markup"] = reply_markup
        if disable_web_page_preview:
            payload["disable_web_page_preview"] = True
        return await self._execute_request("sendMessage", payload)

    async def send_admin_alert(self, text):
        admin_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        if not admin_id: return
        payload = {"chat_id": admin_id, "text": f"🛠️ <b>{BOT_NAME} ALERT</b>\n{text}", "parse_mode": "HTML"}
        return await self._execute_request("sendMessage", payload)

    async def _execute_request(self, method, payload, retries=3):
        """Internal helper with Exponential Backoff (Async)."""
        url = f"{self.base_url}/{method}"
        for attempt in range(retries):
            try:
                async with self.session.post(url, json=payload, timeout=15) as r:
                    if r.status == 429:
                        retry_after = (await r.json()).get("parameters", {}).get("retry_after", 5)
                        await asyncio.sleep(retry_after + 1)
                        continue
                    return await r.json()
            except Exception as e:
                if attempt == retries - 1: return None
                await asyncio.sleep(1 * (attempt + 1))
        return None

    async def _send_document(self, chat_id, file_path, caption="Reference Filing Document"):
        if not file_path or not os.path.exists(file_path): return False, "missing"
        await self.ensure_session()
        try:
            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(chat_id))
                form.add_field("caption", caption)
                form.add_field("document", f, filename=os.path.basename(file_path), content_type="application/pdf")
                async with self.session.post(f"{self.base_url}/sendDocument", data=form, timeout=TELEGRAM_DOCUMENT_TIMEOUT_SEC) as r:
                    if r.status == 200: return True, None
                    return False, f"http_{r.status}"
        except Exception as e:
            return False, str(e)

    async def send_report(self, report_text):
        """v5.2: Parallel Signal Dispatch Engine (Faster delivery)."""
        if not self.token: return
        active_users = self.db.get_active_users() if self.db else []
        
        async def _send_one(cid):
            user_code = self.db.get_referral_code(cid)
            bot_info = await self._execute_request("getMe", {})
            bot_username = bot_info["result"]["username"] if bot_info and "result" in bot_info else "BulkBeatTV_Bot"
            
            referral_nudge = f"\n\n🎁 <a href='https://t.me/{bot_username}?start=ref_{user_code}'>Refer a Friend & Earn</a>"
            final_report = report_text + referral_nudge

            async with self.broadcast_semaphore:
                res = await self._send_raw(cid, final_report, disable_web_page_preview=True)
                await asyncio.sleep(1.0) # v5.2: Strict throttling for Semaphore(30)
                return res

        # Dispatch all in parallel with semaphore throttling
        await asyncio.gather(*[_send_one(cid) for cid in active_users])
        logger.info(f"Broadcasted report to {len(active_users)} active users.")

    async def send_signal(self, item, analysis, pdf_path=None):
        """v15.0: Enhanced Signal Dispatcher (Async)."""
        if not self.token: return False

        symbol = html.escape(str(analysis.get("symbol", "N/A")))
        trigger = html.escape(str(analysis.get("trigger", "N/A")))
        impact_score = analysis.get("impact_score", 0)
        sentiment = html.escape(str(analysis.get("sentiment", "Neutral")))
        is_big_ticket = analysis.get("is_big_ticket", False)
        source = item.get("source", "NSE").upper()
        
        url = item.get("url")
        if url and not url.startswith("http"):
            url = f"https://nsearchives.nseindia.com/corporate/{url}"

        # v5.9: Professional Intelligence Branding (Unified Header)
        header = f"🛰️ <b>{symbol.upper()} | Bulkbeat TV</b>"
        if is_big_ticket: header = f"🔥🔥 <b>BIG TICKET: {symbol.upper()} | Bulkbeat TV</b>"

        message = (
            f"{header} | Intelligence Engine\n"
            f"────────────────────────\n"
            f"🎯 <b>TRIGGER:</b> {trigger}\n"
            f"📊 <b>IMPACT:</b> {impact_score}/10\n"
            f"🧠 <b>SENTIMENT:</b> {sentiment}\n"
            f"────────────────────────\n"
            f"👉 <a href='{url or '#'}'>Reference Filing</a>\n\n"
            f"⚖️ <i>Bulkbeat TV — Non-SEBI Institutional Insights</i>"
        )

        # v8.0: Mirror signal to Supabase Outbox
        if self.db:
            self.db.add_sync_outbox_row("signals", f"{symbol}_{int(time.time())}", {
                "symbol": symbol,
                "impact_score": impact_score,
                "sentiment": sentiment,
                "trigger": trigger,
                "url": url
            })

        active_users = self.db.get_active_users() if self.db else []
        bot_info = await self._execute_request("getMe", {})
        bot_username = bot_info["result"]["username"] if bot_info and "result" in bot_info else "BulkBeatTV_Bot"
        
        async def _dispatch_one(chat_id):
            # v8.0: Appending personalized referral link to each message
            user_code = self.db.get_referral_code(chat_id)
            referral_link = f"https://t.me/{bot_username}?start=ref_{user_code}"
            referral_nudge = f"\n\n📰 <a href='{url}'>Source</a> | 👥 <a href='{referral_link}'>Share & Earn</a>"
            final_message = message + referral_nudge

            async with self.broadcast_semaphore:
                # 1. Send text signal
                await self._send_raw(chat_id, final_message, disable_web_page_preview=True)
                
                # 2. Attach PDF if applicable
                from nse_monitor.config import TELEGRAM_SEND_PDF
                if TELEGRAM_SEND_PDF and pdf_path and os.path.exists(pdf_path):
                    try:
                        file_size = os.path.getsize(pdf_path) / (1024 * 1024)
                        if file_size < 5:
                            caption = f"Filings: {symbol.upper()} | Score: {impact_score}/10"
                            await self._send_document(chat_id, pdf_path, caption=caption)
                    except: pass
                
                # Strict throttling to stay within global Telegram rate limits (30/sec)
                # With Semaphore(30), a 1s sleep ensures exactly 30 msg/sec.
                await asyncio.sleep(1.0)

        # Fire all parallel tasks
        await asyncio.gather(*[_dispatch_one(cid) for cid in active_users])
        return True

    @rate_limit(max_calls=10, period=60)
    async def _handle_history(self, chat_id):
        """Displays user's successful payment history (v12.0)."""
        history = self.db.get_user_payment_history(chat_id)
        if not history:
            msg = (
                "📜 <b>TRANSCRIPT HISTORY</b>\n"
                "────────────────────────\n"
                "<i>No successful transactions found for your ID.</i>\n\n"
                "💡 If you recently paid, use /verify to sync."
            )
            await self._send_raw(chat_id, msg)
            return

        msg = "📜 <b>TRANSACTION HISTORY</b>\n────────────────────────\n"
        for link_id, days, date_str in history[:10]: # Last 10
            try:
                date_ts = datetime.fromisoformat(date_str).strftime("%d %b, %H:%M")
            except:
                date_ts = date_str
            
            msg += f"✅ <b>+{days} Days</b> | <code>{link_id[-8:]}</code>\n"
            msg += f"   📅 {date_ts}\n\n"
        
        msg += "────────────────────────\n"
        msg += "📈 <i>Thank you for choosing Bulkbeat TV Professional.</i>"
        await self._send_raw(chat_id, msg)

    @rate_limit(max_calls=5, period=60)
    async def _handle_billing_history(self, chat_id):
        """Displays the 'Hisab' audit trail for the user (v2.0)."""
        logs = self.db.get_billing_logs(chat_id, limit=8)
        
        if not logs:
            msg = (
                "📝 <b>BILLING AUDIT LOGS</b>\n"
                "────────────────────────\n"
                "<i>No billing activity found in the current audit period.</i>\n\n"
                "💡 Credits are only deducted on active NSE trading days."
            )
            await self._send_raw(chat_id, msg)
            return

        msg = "📝 <b>BILLING AUDIT LOGS</b>\n────────────────────────\n"
        for evt, amt, reason, bal, date_str in logs:
            icon = "➖" if evt == "DEBIT" else "➕"
            try:
                date_ts = datetime.fromisoformat(date_str).strftime("%d %b, %H:%M")
            except:
                date_ts = date_str
            
            msg += f"{icon} <b>{amt} Market Day(s)</b> | {reason}\n"
            msg += f"   📅 {date_ts} | Bal: {bal}\n\n"
            
        msg += "────────────────────────\n"
        msg += "⚖️ <i>Internal Ledger transparency verified.</i>"
        await self._send_raw(chat_id, msg)

    # @rate_limit(max_calls=5, period=120) # Stricter limit for heavy NSE scraping
    # async def _handle_bulk_deals(self, chat_id):
    #     """Fetches bulk deals and always replies (live or cached)."""
    #     await self._send_raw(chat_id, "⏳ <b>Fetching today's bulk deals...</b>")
    #     try:
    #         if not self.nse_client: return
    #         now = datetime.now(self.ist)
    #         date_str = now.strftime("%d-%m-%Y")
    #         url = f"https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from={date_str}&to={date_str}"
    #         data = await self.nse_client.get_json(url, referer="https://www.nseindia.com/report-detail/display-bulk-and-block-deals")
    #         deals = data.get("data", []) if data else []

    #         if not deals:
    #             await self._send_raw(chat_id, "ℹ️ <b>No Bulk Deals reported so far today.</b>\nCheck back after market hours (4:30 PM).")
    #             return

    #         msg = "📈 <b>TODAY'S BIG DEALS (Live)</b>\n────────────────────────\n"
    #         for d in deals[:10]:
    #             symbol = d.get("BD_SYMBOL", d.get("symbol", "N/A"))
    #             client = d.get("BD_CLIENT_NAME", d.get("clientName", "Unknown"))
    #             bs = d.get("BD_BUY_SELL", d.get("buySellFlag", "BUY"))
    #             qty = int(d.get("BD_QTY_TRD", d.get("quantityTraded", 0)))
    #             price = float(d.get("BD_TP_WATP", d.get("tradePrice", 0)))
    #             val_cr = (qty * price) / 1_00_00_000
                
    #             icon = "🟢" if bs == "BUY" else "🔴"
    #             msg += f"{icon} <b>{symbol}</b> | {client}\n"
    #             msg += f"   {bs} {qty:,} @ ₹{price:.1f} (₹{val_cr:.1f} Cr)\n\n"
            
    #         msg += "────────────────────────\n💡 <i>Real-time Institutional Flow</i>"
    #         await self._send_raw(chat_id, msg)
    #     except Exception as e:
    #         logger.error(f"Bulk deal fetch failed: {e}")
    #         await self._send_raw(chat_id, "⚠️ Error fetching NSE data.")

    @rate_limit(max_calls=5, period=60)
    async def _handle_upcoming(self, chat_id):
        """Placeholder for Corporate Calendar."""
        await self._send_raw(chat_id, "🗓️ <b>Corporate Calendar</b>\nFeature coming soon. Stay tuned!")

    def _sanitize_payload(self, payload):
        """Ensures all values in payload are Telegram-safe."""
        if not isinstance(payload, dict): return payload
        return {k: (v if not isinstance(v, str) else v[:4000]) for k, v in payload.items()}
