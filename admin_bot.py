import logging
import aiohttp
import asyncio
import time
import os
import json
import html
import psutil
import shutil
from datetime import datetime
import pytz
import bcrypt
import atexit
from nse_monitor.config import TELEGRAM_ADMIN_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, TELEGRAM_ADMIN_CHAT_IDS, ADMIN_PASSWORD_HASH, BOT_NAME, TELEGRAM_BOT_TOKEN, ADMIN_SESSION_TIMEOUT_MINUTES
from nse_monitor.database import Database

# Logging Setup
def ist_time(*args):
    return datetime.now(pytz.timezone('Asia/Kolkata')).timetuple()

logging.Formatter.converter = ist_time
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("NSEAdmin")
ALLOWED_AI_THRESHOLDS = {"4", "6", "8"}


def _admin_pid_file():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "admin_bot.pid"))


def _cleanup_admin_pid(pid_file):
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except OSError as e:
        logger.warning("PID cleanup failed: %s", e)


def ensure_single_admin_instance():
    pid_file = _admin_pid_file()
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                logger.error("Admin bot already running (PID %s). Exiting.", old_pid)
                return False
            _cleanup_admin_pid(pid_file)
        except Exception:
            _cleanup_admin_pid(pid_file)

    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: _cleanup_admin_pid(pid_file))
    return True

class AdminPanel:
    def __init__(self):
        # v2.0: Separate UI token and Broadcast token
        self.token = TELEGRAM_ADMIN_BOT_TOKEN or TELEGRAM_BOT_TOKEN
        self.signal_bot_token = TELEGRAM_BOT_TOKEN
        
        self.owner_id = str(TELEGRAM_ADMIN_CHAT_ID)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.signal_bot_url = f"https://api.telegram.org/bot{self.signal_bot_token}"
        self.broadcast_url = f"{self.signal_bot_url}/sendMessage"
        
        self.db = Database()
        self.last_update_id = 0
        self.session = None  # Created in run()
        self.failed_logins = {}  # chat_id: [timestamps]

    def _repair_mojibake_text(self, value):
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

    async def _set_latest_offset(self):
        """Skip all stale messages on startup (Rule #24)."""
        try:
            url = f"{self.base_url}/getUpdates"
            async with self.session.get(url, params={"offset": -1, "limit": 1}, timeout=5) as resp:
                data = await resp.json()
                if data.get("ok") and data.get("result"):
                    self.last_update_id = data["result"][0]["update_id"]
                    logger.info(f"Admin Bot Offset Synced: {self.last_update_id}")
        except Exception as e:
            logger.warning(f"Offset sync failed: {e}")

    async def _clear_webhook(self):
        """Ensure getUpdates polling is not blocked by an active webhook."""
        try:
            url = f"{self.base_url}/deleteWebhook"
            async with self.session.post(url, json={"drop_pending_updates": False}, timeout=8) as resp:
                await resp.text()
            logger.info("Admin Bot: Webhook cleared for long-polling mode.")
        except Exception as e:
            logger.warning(f"Admin Bot: deleteWebhook failed: {e}")

    def is_admin(self, chat_id):
        cid = str(chat_id)
        # 1. Owner bypass (checks both single ID and list)
        if cid == self.owner_id or cid in TELEGRAM_ADMIN_CHAT_IDS:
            return True
        # 2. Database session check (Persistent & Shared)
        return self.db.is_admin_session_valid(cid, timeout_minutes=ADMIN_SESSION_TIMEOUT_MINUTES)

    async def run(self):
        logger.info(f"--- {BOT_NAME} | Follow the Beat of Big Money | ADMIN ONLINE ---")
        if self.owner_id:
            logger.info(f"Owner Auto-Login: {self.owner_id}")
        
        async with aiohttp.ClientSession() as session:
            self.session = session
            await self._clear_webhook()
            await self._set_latest_offset()
            
            while True:
                try:
                    updates = await self._get_updates()
                    for update in updates:
                        self.last_update_id = update["update_id"]
                        if "message" in update:
                            await self._handle_message(update["message"])
                        elif "callback_query" in update:
                            await self._handle_callback(update["callback_query"])
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Admin Main Loop Error: {e}")
                    await asyncio.sleep(5)

    async def _get_updates(self):
        url = f"{self.base_url}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 20}
        try:
            async with self.session.get(url, params=params, timeout=30) as resp:
                data = await resp.json()
                return data.get("result", []) if data.get("ok") else []
        except Exception as e:
            logger.error(f"Failed to fetch updates: {e}")
            return []

    async def _handle_message(self, msg):
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        
        # 1. Login Logic (Multi-User v2.0 with Bcrypt & Brute Force Protection)
        if text.startswith("/login"):
            from nse_monitor.config import ADMIN_PASSWORD_HASH
            
            # Security: Delete password message
            await self._delete_message(chat_id, msg["message_id"])

            now = time.time()
            attempts = [t for t in self.failed_logins.get(chat_id, []) if now - t < 900] # 15 min window
            if len(attempts) >= 3:
                wait_sec = int(900 - (now - attempts[0]))
                await self._send(chat_id, f"🚫 <b>Security Lockout.</b> Too many failed attempts. Try again in {wait_sec // 60} minutes.")
                return

            parts = text.split()
            if len(parts) < 2:
                await self._send(chat_id, "❌ Usage: <code>/login <password></code>")
                return
                
            provided_password = parts[1]
            
            # Check Bcrypt Hash
            if not ADMIN_PASSWORD_HASH:
                await self._send(chat_id, "⚠️ <b>System Error:</b> ADMIN_PASSWORD_HASH not configured.")
                return
                
            try:
                is_valid = bcrypt.checkpw(provided_password.encode('utf-8'), ADMIN_PASSWORD_HASH.encode('utf-8'))
            except Exception as e:
                logger.error(f"Admin Bcrypt Error: {e}")
                is_valid = False

            if is_valid:
                self.failed_logins.pop(chat_id, None)
                self.db.set_admin_session(chat_id)
                await self._send(chat_id, "<b>Authentication Successful!</b>\nYou now have persistent admin access.")
                await self._send_main_menu(chat_id)
                logger.warning(f"New Admin Login: {chat_id}")
            else:
                self.failed_logins.setdefault(chat_id, []).append(now)
                remaining = max(0, 3 - len(self.failed_logins[chat_id]))
                await self._send(chat_id, f"<b>Invalid Credentials.</b> {remaining} attempts remaining.")
            return

        # 2. Admin Command Guard
        if not self.is_admin(chat_id):
            await self._send(chat_id, "<b>Access Denied.</b>\nPlease use <code>/login <password></code>")
            return

        # 3. Command Router
        if text == "/start" or text == "/admin":
            await self._send_main_menu(chat_id)
        elif text == "/status":
            await self._handle_status(chat_id)
        elif text == "/pulse" or text == "/health":
            await self._handle_pulse(chat_id)
        elif text == "/users":
            await self._handle_users(chat_id)
        elif text.startswith("/find"):
            await self._handle_find(chat_id, text)
        elif text.startswith("/grant"):
            await self._handle_grant(chat_id, text)
        elif text.startswith("/broadcast"):
            await self._handle_broadcast(chat_id, text)
        elif text == "/logout":
            self.db.clear_admin_session(chat_id)
            await self._send(chat_id, "<b>Logged Out.</b> Session cleared.")

    async def _handle_callback(self, cb):
        from_id = str(cb["from"]["id"])
        chat_id = from_id # Private chat context
        data = cb["data"]
        
        if not self.is_admin(from_id):
            await self._answer_callback(cb["id"], "Session Expired! Please login.")
            return

        if data == "menu_status":
            await self._handle_status(chat_id)
        elif data == "menu_list" or data == "menu_users":
            await self._handle_list(chat_id, 0)
        elif data == "menu_broadcast":
            await self._send(chat_id, "Usage: <code>/broadcast TITLE | MESSAGE</code>\nThis will notify ALL active subscribers.")
        elif data == "menu_config":
            await self._show_config_menu(chat_id)
        elif data == "menu_hisab":
            await self._handle_global_hisab(chat_id)
        elif data == "menu_rescue":
            await self._handle_system_rescue(chat_id)
        elif data.startswith("set_threshold_"):
            val = data.split("_")[2]
            if val not in ALLOWED_AI_THRESHOLDS:
                await self._answer_callback(cb["id"], "Invalid threshold value.", show_alert=True)
                return
            self.db.set_config("ai_threshold", val)
            await self._answer_callback(cb["id"], f"OK. AI Threshold set to {val}")
            # v6.7: Immediate State Override (Prevent DB-Lag Ghosting)
            await self._show_config_menu(chat_id, edit_message_id=cb["message"]["message_id"], override_threshold=val)
        elif data == "toggle_media_mute":
            current = self.db.get_config("media_mute", "0")
            new_val = "1" if current == "0" else "0"
            self.db.set_config("media_mute", new_val)
            await self._answer_callback(cb["id"], f"OK. Media Mute: {'ON' if new_val == '1' else 'OFF'}")
            await self._show_config_menu(chat_id, edit_message_id=cb["message"]["message_id"], override_mute=new_val)

        # v8.0: Free Trial Toggle
        elif data == "toggle_free_trial":
            current_trial = self.db.is_free_trial_enabled()
            new_trial = not current_trial
            self.db.set_free_trial_enabled(new_trial, admin_chat_id=from_id)
            label = "ON" if new_trial else "OFF"
            await self._answer_callback(cb["id"], f"Free Trial toggled {label}. Affects new users only.", show_alert=True)
            await self._send_main_menu(chat_id)

        # v8.0: Referral System menu
        elif data == "menu_referral":
            await self._show_referral_menu(chat_id)
        elif data == "ref_list_referred":
            await self._show_referred_users(chat_id, mode="all", offset=0)
        elif data == "ref_list_converted":
            await self._show_referred_users(chat_id, mode="converted", offset=0)
        elif data == "ref_list_nonconverted":
            await self._show_referred_users(chat_id, mode="non_converted", offset=0)
        elif data == "ref_list_pendingtrial":
            await self._show_referred_users(chat_id, mode="pending_trial", offset=0)
        elif data == "ref_leaderboard":
            await self._show_referrer_leaderboard(chat_id)
        elif data.startswith("ref_page_"):
            payload = data[len("ref_page_"):]
            mode, page_str = payload.rsplit("_", 1)
            page = int(page_str)
            await self._show_referred_users(chat_id, mode=mode, offset=page * 10)
        elif data.startswith("ref_user_"):
            uid = data.split("ref_user_")[1]
            await self._show_referral_user_detail(chat_id, uid)
        elif data.startswith("ref_payout_"):
            uid = data.split("ref_payout_")[1]
            await self._execute_referral_payout(chat_id, from_id, uid)
        elif data.startswith("ref_discount_"):
            uid = data.split("ref_discount_")[1]
            await self._execute_referral_discount(chat_id, from_id, uid)
        elif data.startswith("ref_setpct_"):
            uid = data.split("ref_setpct_")[1]
            await self._show_referral_discount_options(chat_id, uid)
        elif data.startswith("ref_pct_"):
            _, _, uid, pct = data.split("_", 3)
            await self._execute_set_discount_percent(chat_id, from_id, uid, pct)
        elif data.startswith("ref_reject_"):
            uid = data.split("ref_reject_")[1]
            await self._execute_reject_discount(chat_id, from_id, uid)
        elif data.startswith("ref_adjust_"):
            uid = data.split("ref_adjust_")[1]
            await self._show_manual_adjust_options(chat_id, uid)
        elif data.startswith("ref_adjval_"):
            _, _, uid, amt = data.split("_", 3)
            await self._execute_manual_adjust(chat_id, from_id, uid, amt)

        elif data.startswith("list_page_"):
            page = int(data.split("_")[2])
            offset = page * 10
            await self._handle_list(chat_id, offset)
        elif data.startswith("manage_"):
            uid = data.split("_")[1]
            await self._show_manage_menu(chat_id, uid)
        elif data.startswith("reset_"):
            uid = data.split("_")[1]
            await self._execute_reset(chat_id, uid)
        elif data.startswith("deactivate_"):
            uid = data.split("_")[1]
            await self._execute_deactivate(chat_id, uid)
        elif data.startswith("plans_"):
            uid = data.split("_")[1]
            await self._show_plan_options(chat_id, uid)
        elif data.startswith("grant_"):
            parts = data.split("_")
            if len(parts) == 3:
                _, uid, days_str = parts
                try:
                    days = int(days_str)
                    # Security: Strict whitelist of allowed grant values
                    if days in [2, 7, 28, 336]:
                        await self._execute_grant_interactive(chat_id, uid, days)
                    else:
                        logger.error(f"Malicious callback manipulation attempt from {from_id}: {data}")
                        await self._answer_callback(cb["id"], "Error: Invalid grant value.")
                except ValueError: pass
        
        elif data == "menu_main":
            await self._send_main_menu(chat_id)
        elif data == "action_vacuum":
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: self.db.conn.execute("VACUUM"))
                await self._answer_callback(cb["id"], "OK. Database vacuum complete.", show_alert=True)
            except Exception as e:
                await self._answer_callback(cb["id"], f"Error: {e}", show_alert=True)
        elif data == "action_purge":
            try:
                deleted = self.db.purge_old_data(days=30)
                await self._answer_callback(cb["id"], f"OK. Purge complete: {deleted} items removed.", show_alert=True)
            except Exception as e:
                await self._answer_callback(cb["id"], f"Purge failed: {e}", show_alert=True)
        elif data == "action_sync_supabase":
            try:
                count = self.db.backfill_supabase_outbox()
                await self._answer_callback(cb["id"], f"OK. {count} users queued for Supabase sync.", show_alert=True)
            except Exception as e:
                await self._answer_callback(cb["id"], f"Sync failed: {e}", show_alert=True)
        elif data == "action_sync_holidays":
            from nse_monitor.trading_calendar import TradingCalendar
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, TradingCalendar.sync_from_nse)
            if success:
                await self._answer_callback(cb["id"], "OK. NSE holidays synced.", show_alert=True)
            else:
                await self._answer_callback(cb["id"], "Sync failed. Check logs.", show_alert=True)
        
        await self._answer_callback(cb["id"])

    async def _send_main_menu(self, chat_id):
        trial_on = self.db.is_free_trial_enabled()
        trial_label = "Free Trial: ON" if trial_on else "Free Trial: OFF"
        text = (
            f"<b>{BOT_NAME} INTELLIGENCE GATEWAY (v12.0)</b>\n"
            f"------------------------------\n"
            f"<b>Commands:</b>\n"
            f"- <code>/users</code> : Active User Summary\n"
            f"- <code>/find &lt;id/name&gt;</code> : Search DB\n"
            f"- <code>/grant &lt;id&gt; &lt;days&gt;</code> : Manual Credit\n"
            f"- <code>/broadcast &lt;msg&gt;</code> : Global Signal\n"
            f"- <code>/status</code> : System Health\n\n"
            f"<b>Free Trial:</b> {'<b>ON</b> (new users get trial days)' if trial_on else '<b>OFF</b> (no trial for new users)'}\n"
            f"Select an action below:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "System Status", "callback_data": "menu_status"}, {"text": "Bot Config", "callback_data": "menu_config"}],
                [{"text": "User Audit", "callback_data": "menu_list"}, {"text": "Global Audit", "callback_data": "menu_hisab"}],
                [{"text": "Send Signal", "callback_data": "menu_broadcast"}, {"text": "DB Rescue", "callback_data": "menu_rescue"}],
                [{"text": trial_label, "callback_data": "toggle_free_trial"}, {"text": "Referral System", "callback_data": "menu_referral"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _show_config_menu(self, chat_id, edit_message_id=None, override_threshold=None, override_mute=None, override_trial=None):
        # v7.1: State Synthesis (Priority: Override > DB > Default)
        thresh = override_threshold or self.db.get_config("ai_threshold", "8")
        if thresh not in ALLOWED_AI_THRESHOLDS:
            thresh = "8"
        mute = override_mute or self.db.get_config("media_mute", "0")
        trial_on = (override_trial is not None and override_trial) or (override_trial is None and self.db.is_free_trial_enabled())

        mute_label = "UNMUTE Media" if mute == "1" else "MUTE Media"
        trial_label = "Free Trial: ON  [toggle OFF]" if trial_on else "Free Trial: OFF [toggle ON]"
        ist_now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')
        sync_icon = "S" if thresh == "8" else ("OK" if (override_threshold or override_mute) else "~")

        text = (
            f"<b>{BOT_NAME} | LIVE CONFIG (v8.0)</b>\n"
            f"------------------------------\n"
            f"<b>Current Threshold:</b> {thresh}/10 [{sync_icon}]\n"
            f"<b>Media Source:</b> {'MUTED (Official Only)' if mute == '1' else 'ACTIVE'}\n"
            f"<b>Free Trial:</b> {'ON — new users get trial days' if trial_on else 'OFF — no trial for new users'}\n"
            f"<b>Last Updated:</b> <code>{ist_now} (IST)</code>\n"
            f"------------------------------\n"
            f"<i>Settings apply instantly. Free Trial affects new users only.</i>"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "Threshold: 4 (Aggressive)", "callback_data": "set_threshold_4"}],
                [{"text": "Threshold: 6 (Balanced)", "callback_data": "set_threshold_6"}],
                [{"text": "Threshold: 8 (Ultra Strict)", "callback_data": "set_threshold_8"}],
                [{"text": mute_label, "callback_data": "toggle_media_mute"}],
                [{"text": trial_label, "callback_data": "toggle_free_trial"}],
                [{"text": "Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        await self._send(chat_id, text, keyboard, edit_message_id=edit_message_id)

    async def _handle_global_hisab(self, chat_id):
        debits, users = self.db.get_global_hisab(days=1)
        debits_week, users_week = self.db.get_global_hisab(days=7)
        
        text = (
            f"<b>GLOBAL AUDIT (HISAB)</b>\n"
            f"------------------------------\n"
            f"<b>Today's Volume:</b>\n"
            f"Deducted: {debits} Market Days\n"
            f"Unique Users: {users}\n\n"
            f"<b>Last 7 Days:</b>\n"
            f"Total Debits: {debits_week}\n"
            f"Unique Reach: {users_week}\n"
            f"------------------------------\n"
            f"<i>Internal Finance Audit Only</i>"
        )
        await self._send(chat_id, text)

    async def _handle_system_rescue(self, chat_id):
        text = (
            "<b>SYSTEM RESCUE & MAINTENANCE</b>\n"
            "------------------------------\n"
            "<b>WARNING:</b> These actions are destructive or performance intensive.\n\n"
            "<b>1. Repair DB:</b> Runs VACUUM to fix minor corruption.\n"
            "<b>2. Update Holidays:</b> Live Sync from NSE server.\n"
            "<b>3. Purge Engine:</b> Deletes news older than 30 days.\n"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "Run DB Vacuum", "callback_data": "action_vacuum"}],
                [{"text": "Sync NSE Holidays", "callback_data": "action_sync_holidays"}],
                [{"text": "Force Supabase Sync", "callback_data": "action_sync_supabase"}],
                [{"text": "Purge Old News", "callback_data": "action_purge"}],
                [{"text": "Back", "callback_data": "menu_main"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _handle_status(self, chat_id):
        total, active = self.db.get_user_stats()
        text = (
            f"<b>PRODUCTION STATUS (v12.0)</b>\n"
            f"------------------------------\n"
            f"<b>Signal Engine:</b> ACTIVE\n"
            f"<b>AI Processor:</b> ONLINE\n\n"
            f"<b>Total Users:</b> {total}\n"
            f"<b>Active Subs:</b> {active}\n"
            f"------------------------------\n"
            f"<i>Bulkbeat TV — Follow the Beat of Big Money News with Smart Money</i>"
        )
        await self._send(chat_id, text)

    async def _handle_list(self, chat_id, offset=0):
        limit = 10
        users = self.db.get_all_users(limit=limit, offset=offset)
        page = offset // limit

        lines = [f"<b>USER AUDIT (Page {page + 1})</b>", "------------------------------"]
        keyboard = {"inline_keyboard": []}

        for u in users:
            uid, name, uname, active, days = u
            has_username = uname and uname not in ("manual_entry", "Unknown", "Legacy", "Sync_Legacy", "None")
            uname_label = f"@{uname}" if has_username else f"...{str(uid)[-6:]}"
            display_name = name if name and name != "Sync_Legacy" else "User"
            icon = "ACTIVE" if active else "INACTIVE"
            lines.append(f"{icon} {display_name} {uname_label} [<code>{uid}</code>] | <b>{days}d</b>")
            keyboard["inline_keyboard"].append([{"text": f"Manage {uname_label}", "callback_data": f"manage_{uid}"}])
        
        nav_buttons = []
        if offset > 0:
            nav_buttons.append({"text": "Prev", "callback_data": f"list_page_{page - 1}"})
        if len(users) == limit:
            nav_buttons.append({"text": "Next", "callback_data": f"list_page_{page + 1}"})
        
        if nav_buttons:
            keyboard["inline_keyboard"].append(nav_buttons)
        if not users:
            lines.append("<i>No more users found.</i>")
        lines.append("------------------------------")
        lines.append("<i>Click user for Manage Menu.</i>")
        await self._send(chat_id, "\n".join(lines), keyboard)

    async def _show_manage_menu(self, chat_id, uid):
        user = self.db.get_user(uid)
        if not user: return
        
        name = user[1]
        text = (
            f"<b>MANAGE USER:</b> {name}\n"
            f"<b>ID:</b> <code>{uid}</code>\n"
            f"<b>Current Balance:</b> {user[4]} days\n"
            f"------------------------------\n"
            f"Select an action to perform:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "Reset to 0 Days", "callback_data": f"reset_{uid}"}],
                [{"text": "Deactivate Account", "callback_data": f"deactivate_{uid}"}],
                [{"text": "Add Plan (Grant Days)", "callback_data": f"plans_{uid}"}],
                [{"text": "Back to List", "callback_data": "menu_list"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _show_plan_options(self, chat_id, uid):
        text = f"<b>SELECT PLAN TO GRANT:</b>\nGrant days to user <code>{uid}</code> instantly."
        keyboard = {
            "inline_keyboard": [
                [{"text": "Star Plan (+2d)", "callback_data": f"grant_{uid}_2"}],
                [{"text": "Growth Plan (+7d)", "callback_data": f"grant_{uid}_7"}],
                [{"text": "Professional (+28d)", "callback_data": f"grant_{uid}_28"}],
                [{"text": "Institutional (+336d)", "callback_data": f"grant_{uid}_336"}],
                [{"text": "Back", "callback_data": f"manage_{uid}"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _execute_deactivate(self, chat_id, uid):
        self.db.toggle_user_status(uid, 0)
        await self._send(chat_id, f"<b>Deactivated:</b> {uid}. Signals paused.")
        await self._show_manage_menu(chat_id, uid)

    async def _execute_reset(self, chat_id, uid):
        self.db.reset_user_days(uid)
        await self._send(chat_id, f"<b>Reset:</b> {uid} balance is now 0.")
        await self._show_manage_menu(chat_id, uid)

    async def _execute_grant_interactive(self, chat_id, uid, days):
        self.db.add_working_days(uid, days)
        self.db.toggle_user_status(uid, 1)
        await self._send(chat_id, f"<b>Granted {days}d</b> to <code>{uid}</code>.")
        msg = (
            f"<b>Manual Account Activation</b>\n"
            f"------------------------------\n"
            f"The Administrator has credited your account with <b>{days} Market Days</b>.\n\n"
            f"Your professional intelligence engine is now <b>LIVE</b>."
        )
        await self._notify_user_via_signal_bot(uid, msg)
        await self._show_manage_menu(chat_id, uid)

    async def _handle_find(self, chat_id, text):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(chat_id, "Usage: <code>/find &lt;id/name&gt;</code>")
            return
        
        query = parts[1].strip()
        results = self.db.search_users(query)
        if not results:
            await self._send(chat_id, f"No results for: <code>{query}</code>")
            return
        
        text_out = f"<b>Search:</b> <code>{query}</code>\n------------------------------\n"
        keyboard = {"inline_keyboard": []}
        for uid, name, uname, active, days in results:
            icon = "ACTIVE" if active else "INACTIVE"
            text_out += f"{icon} {name} [<code>{uid}</code>] | {days}d\n"
            keyboard["inline_keyboard"].append([{"text": f"Manage {name}", "callback_data": f"manage_{uid}"}])
        
        await self._send(chat_id, text_out, keyboard)

    async def _handle_users(self, chat_id):
        users = self.db.get_all_users(limit=15)
        lines = ["<b>LATEST USERS</b>", "------------------------------"]
        for u in users:
            uid, name, uname, active, days = u
            icon = "ACTIVE" if active else "INACTIVE"
            lines.append(f"{icon} {name} [<code>{uid}</code>] | {days}d")
        await self._send(chat_id, "\n".join(lines))

    async def _handle_grant(self, chat_id, text):
        parts = text.split()
        if len(parts) < 3:
            await self._send(chat_id, "Usage: <code>/grant &lt;id&gt; &lt;days&gt;</code>")
            return
        target_id, days = parts[1], parts[2]
        self.db.add_working_days(target_id, int(days))
        self.db.toggle_user_status(target_id, 1)
        await self._send(chat_id, f"Granted {days}d to {target_id}.")
        msg = f"Admin credited your account with <b>{days} Market Days</b>. LIVE."
        await self._notify_user_via_signal_bot(target_id, msg)

    async def _notify_user_via_signal_bot(self, user_id, text):
        payload = {"chat_id": user_id, "text": self._repair_mojibake_text(text), "parse_mode": "HTML"}
        try:
            async with self.session.post(f"{self.signal_bot_url}/sendMessage", json=payload, timeout=5) as resp:
                await resp.text()
        except Exception as e:
            logger.warning("notify_user_via_signal_bot failed for %s: %s", user_id, e)

    async def _handle_broadcast(self, chat_id, text):
        full_content = text.replace("/broadcast", "").strip()
        if not full_content:
            await self._send(chat_id, "Usage: <code>/broadcast TITLE | MESSAGE</code>")
            return
        
        # v7.8: Robust Header Injection
        if " | " in full_content:
            parts = full_content.split(" | ", 1)
            # This part REPLACES 'SIGNAL UPDATE'
            header_title = parts[0].strip().upper()
            msg_body = parts[1].strip()
        else:
            header_title = "SIGNAL UPDATE"
            msg_body = full_content
            
        if len(msg_body) > 1000:
            await self._send(chat_id, "❌ <b>Error:</b> Broadcast too long.")
            return
        
        active_users = self.db.get_active_users()
        count = 0
        formatted_header = f"<b>{BOT_NAME} | {header_title}</b>"
        final_msg = f"{formatted_header}\n------------------------------\n{msg_body}"
        
        for uid in active_users:
            try:
                await self._send(uid, final_msg, use_signal_bot=True)
                count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning("Broadcast failed for %s: %s", uid, e)
        await self._send(chat_id, f"✅ <b>Success:</b> Broadcast sent to {count} users.\n<b>Header Used:</b> {header_title}")

    async def _send(self, chat_id, text, keyboard=None, use_signal_bot=False, edit_message_id=None):
        payload = {"chat_id": chat_id, "text": self._repair_mojibake_text(text), "parse_mode": "HTML"}
        if keyboard: payload["reply_markup"] = keyboard
        
        if edit_message_id:
            payload["message_id"] = edit_message_id
            url = f"{self.base_url}/editMessageText"
        else:
            url = self.broadcast_url if use_signal_bot else f"{self.base_url}/sendMessage"
            
        try:
            async with self.session.post(url, json=payload, timeout=10) as resp:
                await resp.text()
        except Exception as e:
            logger.error(f"Send failed: {e}")

    async def _answer_callback(self, cb_id, text=None, show_alert=False):
        payload = {"callback_query_id": cb_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        try:
            async with self.session.post(f"{self.base_url}/answerCallbackQuery", json=payload, timeout=5) as resp:
                await resp.text()
        except Exception as e:
            logger.warning("answerCallbackQuery failed: %s", e)

    async def _delete_message(self, chat_id, message_id):
        try:
            async with self.session.post(f"{self.base_url}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=5) as resp:
                await resp.text()
        except Exception as e:
            logger.warning("deleteMessage failed: %s", e)

    async def _show_referral_menu(self, chat_id):
        text = (
            f"<b>{BOT_NAME} | REFERRAL SYSTEM</b>\n"
            f"------------------------------\n"
            f"Track and manage affiliate performance.\n"
            f"Reward top referrers and manage payouts."
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "Referred Users List", "callback_data": "ref_list_referred"}],
                [{"text": "Converted Users", "callback_data": "ref_list_converted"}, {"text": "Non-Converted", "callback_data": "ref_list_nonconverted"}],
                [{"text": "Pending Trial Expiry", "callback_data": "ref_list_pendingtrial"}],
                [{"text": "Referrer Leaderboard", "callback_data": "ref_leaderboard"}],
                [{"text": "Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _show_referred_users(self, chat_id, mode="all", offset=0):
        limit = 10
        users = self.db.get_referred_users_filtered(mode=mode, limit=limit, offset=offset)
        page = offset // limit

        mode_titles = {
            "all": "REFERRED USERS",
            "converted": "CONVERTED USERS",
            "non_converted": "NON-CONVERTED USERS",
            "pending_trial": "PENDING TRIAL EXPIRY",
        }

        lines = [f"<b>{mode_titles.get(mode, 'REFERRED USERS')} (Page {page + 1})</b>", "------------------------------"]
        keyboard = {"inline_keyboard": []}

        for u in users:
            uid, name, uname, active, days, ref_code, total_paid, reg_at = u
            status = "✅" if active else "❌"
            lines.append(f"{status} {name} [<code>{uid}</code>]")
            lines.append(f"   Code: <code>{ref_code}</code> | Paid: ₹{total_paid}")
            keyboard["inline_keyboard"].append([{"text": f"Manage {name}", "callback_data": f"ref_user_{uid}"}])

        nav_buttons = []
        if offset > 0:
            nav_buttons.append({"text": "Prev", "callback_data": f"ref_page_{mode}_{page - 1}"})
        if len(users) == limit:
            nav_buttons.append({"text": "Next", "callback_data": f"ref_page_{mode}_{page + 1}"})

        if nav_buttons:
            keyboard["inline_keyboard"].append(nav_buttons)
        keyboard["inline_keyboard"].append([{"text": "Back to Referral Menu", "callback_data": "menu_referral"}])

        if not users:
            lines.append("<i>No referred users found.</i>")
        await self._send(chat_id, "\n".join(lines), keyboard)

    async def _show_referrer_leaderboard(self, chat_id):
        leaders = self.db.get_referrer_leaderboard(limit=10)
        lines = ["<b>REFERRER LEADERBOARD</b>", "------------------------------"]

        if not leaders:
            lines.append("<i>No referral activity yet.</i>")
        else:
            for i, (rid, joins, convs, amount) in enumerate(leaders, 1):
                lines.append(f"{i}. <code>{rid}</code> | {joins} j | {convs} c | ₹{amount or 0}")

        keyboard = {"inline_keyboard": [[{"text": "Back", "callback_data": "menu_referral"}]]}
        await self._send(chat_id, "\n".join(lines), keyboard)

    async def _show_referral_user_detail(self, chat_id, uid):
        user = self.db.get_user(uid)
        if not user: return

        # Outgoing: this user as a referrer
        stats = self.db.get_referral_stats(uid)
        code = self.db.get_referral_code(uid)

        # Incoming: who referred this user
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT referred_by_code, referred_by_user_id, total_paid_amount FROM users WHERE id = ?", (str(uid),))
        row = cursor.fetchone()
        referred_by_code = row[0] if row else None
        referred_by_uid = row[1] if row else None
        total_paid = row[2] if row else 0

        text = (
            f"<b>REFERRAL DETAIL:</b> {user[1]}\n"
            f"<b>ID:</b> <code>{uid}</code>\n"
            f"<b>Own Code:</b> <code>{code}</code>\n"
            f"------------------------------\n"
            f"<b>Referred By:</b> {f'<code>{referred_by_uid}</code> (code: {referred_by_code})' if referred_by_uid else 'Direct signup'}\n"
            f"<b>Total Paid:</b> ₹{total_paid}\n"
            f"------------------------------\n"
            f"<b>As Referrer:</b>\n"
            f"  Joins: {stats['joins']} | Conversions: {stats['conversions']}\n"
            f"  Wallet Balance: ₹{stats['reward_balance']}\n"
            f"------------------------------\n"
            f"Select an action:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "Mark Payout Approved", "callback_data": f"ref_payout_{uid}"}],
                [{"text": "Credit Discount (Manual)", "callback_data": f"ref_discount_{uid}"}],
                [{"text": "Set Plan Discount %", "callback_data": f"ref_setpct_{uid}"}],
                [{"text": "Manual Adjust Wallet", "callback_data": f"ref_adjust_{uid}"}],
                [{"text": "Reject Discount", "callback_data": f"ref_reject_{uid}"}],
                [{"text": "Back to List", "callback_data": "ref_list_referred"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _execute_referral_payout(self, chat_id, admin_id, uid):
        balance = self.db.get_reward_balance(uid)
        if balance <= 0:
            await self._send(chat_id, "❌ User has zero balance.")
            return
            
        # Deduct from ledger
        self.db.add_reward_ledger_entry(uid, "debit", balance, reason="Cash Payout Approved by Admin")
        self.db.log_referral_admin_action(admin_id, uid, "payout_marked", amount_rupees=balance, note="Full balance payout")
        
        await self._send(chat_id, f"✅ <b>Payout Marked:</b> ₹{balance} for <code>{uid}</code>.")
        await self._show_referral_user_detail(chat_id, uid)

    async def _execute_referral_discount(self, chat_id, admin_id, uid):
        balance = self.db.get_reward_balance(uid)
        if balance <= 0:
            await self._send(chat_id, "❌ User has zero reward balance to convert to discount.")
            return
        # Reward balance is already in the ledger as credit; admin confirms it's usable as discount
        self.db.log_referral_admin_action(admin_id, uid, "discount_approved", amount_rupees=balance,
                                          note="Discount wallet credit approved by admin")
        await self._send(chat_id, f"✅ <b>Discount Approved:</b> ₹{balance} wallet credit confirmed for <code>{uid}</code>.\n"
                                  f"Will be auto-deducted on next plan purchase.")
        await self._show_referral_user_detail(chat_id, uid)

    async def _show_referral_discount_options(self, chat_id, uid):
        current = self.db.get_user_discount_percent(uid)
        text = (
            f"<b>SET DISCOUNT PERCENT</b>\n"
            f"User: <code>{uid}</code>\n"
            f"Current one-time discount: <b>{current}%</b>\n\n"
            f"Select discount for next plan purchase:"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "5%", "callback_data": f"ref_pct_{uid}_5"},
                    {"text": "10%", "callback_data": f"ref_pct_{uid}_10"},
                    {"text": "15%", "callback_data": f"ref_pct_{uid}_15"}
                ],
                [
                    {"text": "20%", "callback_data": f"ref_pct_{uid}_20"},
                    {"text": "25%", "callback_data": f"ref_pct_{uid}_25"},
                    {"text": "30%", "callback_data": f"ref_pct_{uid}_30"}
                ],
                [
                    {"text": "50%", "callback_data": f"ref_pct_{uid}_50"},
                    {"text": "Clear (0%)", "callback_data": f"ref_pct_{uid}_0"}
                ],
                [{"text": "Back", "callback_data": f"ref_user_{uid}"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _execute_set_discount_percent(self, chat_id, admin_id, uid, pct):
        try:
            percent = max(0, min(95, int(pct)))
        except ValueError:
            await self._send(chat_id, "❌ Invalid discount percentage.")
            return
        self.db.set_user_discount_percent(uid, percent, admin_chat_id=admin_id)
        await self._send(chat_id, f"✅ One-time discount set: <b>{percent}%</b> for <code>{uid}</code>.")
        await self._show_referral_user_detail(chat_id, uid)

    async def _execute_reject_discount(self, chat_id, admin_id, uid):
        self.db.set_user_discount_percent(uid, 0, admin_chat_id=admin_id)
        await self._send(chat_id, f"✅ Discount rejected/cleared for <code>{uid}</code>.")
        await self._show_referral_user_detail(chat_id, uid)

    async def _show_manual_adjust_options(self, chat_id, uid):
        text = (
            f"<b>MANUAL WALLET ADJUST</b>\n"
            f"User: <code>{uid}</code>\n"
            f"Choose adjustment amount (rupees):"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "+50", "callback_data": f"ref_adjval_{uid}_50"},
                    {"text": "+100", "callback_data": f"ref_adjval_{uid}_100"}
                ],
                [
                    {"text": "-50", "callback_data": f"ref_adjval_{uid}_-50"},
                    {"text": "-100", "callback_data": f"ref_adjval_{uid}_-100"}
                ],
                [{"text": "Back", "callback_data": f"ref_user_{uid}"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _execute_manual_adjust(self, chat_id, admin_id, uid, amt):
        try:
            amount = int(amt)
        except ValueError:
            await self._send(chat_id, "❌ Invalid adjustment amount.")
            return

        entry_type = "adjust"
        self.db.add_reward_ledger_entry(uid, entry_type, amount, reason=f"Manual adjust by admin {admin_id}")
        self.db.log_referral_admin_action(admin_id, uid, "manual_adjust", amount_rupees=amount, note="Wallet manual adjust")
        await self._send(chat_id, f"✅ Wallet adjusted by ₹{amount} for <code>{uid}</code>.")
        await self._show_referral_user_detail(chat_id, uid)

    async def _handle_pulse(self, chat_id):
        await self._send(chat_id, "<b>Industrial Pulse...</b>")
        try:
            from nse_monitor.config import START_TIME
            uptime = time.time() - START_TIME
            d, r = divmod(uptime, 86400)
            h, r = divmod(r, 3600)
            m, _ = divmod(r, 60)
            uptime_str = f"{int(d)}d {int(h)}h {int(m)}m"
            
            from nse_monitor.config import DB_PATH
            db_size = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) / (1024*1024) or 0
            total, used, _ = shutil.disk_usage("/")
            disk_pct = (used / total) * 100
            ram = psutil.virtual_memory().percent
            process = psutil.Process(os.getpid())
            rss = process.memory_info().rss / (1024 * 1024) # MB
            
            last_bk = self.db.get_config("last_backup", "Never")
            if last_bk != "Never":
                last_bk = datetime.fromtimestamp(float(last_bk), tz=pytz.timezone('Asia/Kolkata')).strftime("%d %b, %H:%M")
            
            ist_now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')
            
            msg = (
                f"<b>{BOT_NAME} - INDUSTRIAL PULSE</b>\n"
                f"------------------------------\n"
                f"<b>Uptime:</b> <code>{uptime_str}</code>\n"
                f"<b>DB Size:</b> <code>{db_size:.2f} MB</code>\n"
                f"<b>Disk Used:</b> <code>{disk_pct:.1f}%</code>\n"
                f"<b>RAM Total:</b> <code>{ram}%</code>\n"
                f"<b>Bot RAM:</b> <code>{rss:.1f} MB</code>\n"
                f"<b>Last Backup:</b> <code>{last_bk}</code>\n"
                f"------------------------------\n"
                f"<i>IST: {ist_now}</i>"
            )
            await self._send(chat_id, msg)
        except Exception as e:
            logger.error(f"Pulse failed: {e}")

if __name__ == "__main__":
    try:
        if ensure_single_admin_instance():
            asyncio.run(AdminPanel().run())
    except KeyboardInterrupt:
        pass
