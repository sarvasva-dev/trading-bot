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
from nse_monitor.config import TELEGRAM_ADMIN_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, ADMIN_PASSWORD_HASH, BOT_NAME, TELEGRAM_BOT_TOKEN, ADMIN_SESSION_TIMEOUT_MINUTES
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
        # 1. Owner bypass
        if cid == self.owner_id: return True
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
                remaining = 3 - len(self.failed_logins[chat_id])
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
            await self._send(chat_id, "Usage: <code>/broadcast &lt;message&gt;</code>\nThis will notify ALL active subscribers.")
        elif data == "menu_config":
            await self._show_config_menu(chat_id)
        elif data == "menu_hisab":
            await self._handle_global_hisab(chat_id)
        elif data == "menu_rescue":
            await self._handle_system_rescue(chat_id)
        elif data.startswith("set_threshold_"):
            val = data.split("_")[2]
            self.db.set_config("ai_threshold", val)
            await self._answer_callback(cb["id"], f"OK. AI Threshold set to {val}", show_alert=True)
            await self._show_config_menu(chat_id)
        elif data == "toggle_media_mute":
            current = self.db.get_config("media_mute", "0")
            new_val = "1" if current == "0" else "0"
            self.db.set_config("media_mute", new_val)
            await self._answer_callback(cb["id"], f"OK. Media Mute: {'ON' if new_val == '1' else 'OFF'}", show_alert=True)
            await self._show_config_menu(chat_id)
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
                # Synchronous operation wrapped in executor
                loop = asyncio.get_event_loop()
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
        elif data == "action_sync_holidays":
            from nse_monitor.trading_calendar import TradingCalendar
            # Sync is synchronous requests, wrapping for UI responsiveness
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, TradingCalendar.sync_from_nse)
            if success:
                await self._answer_callback(cb["id"], "OK. NSE holidays synced.", show_alert=True)
            else:
                await self._answer_callback(cb["id"], "Sync failed. Check logs.", show_alert=True)
        
        await self._answer_callback(cb["id"])

    async def _send_main_menu(self, chat_id):
        text = (
            f"<b>{BOT_NAME} ADMIN GUIDE (v12.0 - ASYNC)</b>\n"
            f"------------------------------\n"
            f"<b>Commands:</b>\n"
            f"- <code>/users</code> : Active User Summary\n"
            f"- <code>/find &lt;id/name&gt;</code> : Search DB\n"
            f"- <code>/grant &lt;id&gt; &lt;days&gt;</code> : Manual Credit\n"
            f"- <code>/broadcast &lt;msg&gt;</code> : Global Alert\n"
            f"- <code>/status</code> : System Health\n\n"
            f"Select an action below:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "System Status", "callback_data": "menu_status"}, {"text": "Bot Config", "callback_data": "menu_config"}],
                [{"text": "User Audit", "callback_data": "menu_list"}, {"text": "Global Hisab", "callback_data": "menu_hisab"}],
                [{"text": "Broadcast", "callback_data": "menu_broadcast"}, {"text": "DB Rescue", "callback_data": "menu_rescue"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

    async def _show_config_menu(self, chat_id):
        thresh = self.db.get_config("ai_threshold", "5")
        mute = self.db.get_config("media_mute", "0")
        mute_label = "UNMUTE Media" if mute == "1" else "MUTE Media"
        
        text = (
            f"<b>BOT LIVE CONFIG</b>\n"
            f"------------------------------\n"
            f"<b>Current Threshold:</b> {thresh}/10\n"
            f"<b>Media Source:</b> {'MUTED (Official Only)' if mute == '1' else 'ACTIVE'}\n"
            f"------------------------------\n"
            f"<i>Changes apply instantly to the next cycle.</i>"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "Threshold: 3 (Aggressive)", "callback_data": "set_threshold_3"}],
                [{"text": "Threshold: 5 (Standard)", "callback_data": "set_threshold_5"}],
                [{"text": "Threshold: 7 (Safe)", "callback_data": "set_threshold_7"}],
                [{"text": "Toggle Media Mute", "callback_data": "toggle_media_mute"}],
                [{"text": "Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        await self._send(chat_id, text, keyboard)

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
        
        text = f"<b>USER AUDIT (Page {page + 1})</b>\n------------------------------\n"
        keyboard = {"inline_keyboard": []}
        
        for u in users:
            uid, name, uname, active, days = u
            has_username = uname and uname not in ("manual_entry", "Unknown", "Legacy", "Sync_Legacy", "None")
            uname_label = f"@{uname}" if has_username else f"...{str(uid)[-6:]}"
            display_name = name if name and name != "Sync_Legacy" else "User"
            icon = "ACTIVE" if active else "INACTIVE"
            text += f"{icon} {display_name} {uname_label} [<code>{uid}</code>] | <b>{days}d</b>\n"
            keyboard["inline_keyboard"].append([{"text": f"Manage {uname_label}", "callback_data": f"manage_{uid}"}])
        
        nav_buttons = []
        if offset > 0:
            nav_buttons.append({"text": "Prev", "callback_data": f"list_page_{page - 1}"})
        if len(users) == limit:
            nav_buttons.append({"text": "Next", "callback_data": f"list_page_{page + 1}"})
        
        if nav_buttons: keyboard["inline_keyboard"].append(nav_buttons)
        if not users: text += "<i>No more users found.</i>"
            
        text += "------------------------------\n<i>Click user for Manage Menu.</i>"
        await self._send(chat_id, text, keyboard)

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
        text = "<b>LATEST USERS</b>\n------------------------------\n"
        for u in users:
            uid, name, uname, active, days = u
            icon = "ACTIVE" if active else "INACTIVE"
            text += f"{icon} {name} [<code>{uid}</code>] | {days}d\n"
        await self._send(chat_id, text)

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
        except: pass

    async def _handle_broadcast(self, chat_id, text):
        msg_body = text.replace("/broadcast", "").strip()
        if not msg_body:
            await self._send(chat_id, "Empty broadcast.")
            return
        
        if len(msg_body) > 1000:
            await self._send(chat_id, "❌ <b>Error:</b> Broadcast too long (Max 1000 chars).")
            return

        active_users = self.db.get_active_users()
        count = 0
        for uid in active_users:
            try:
                await self._send(uid, f"<b>ADMIN ANNOUNCEMENT</b>\n------------------------------\n{msg_body}", use_signal_bot=True)
                count += 1
                await asyncio.sleep(0.05)
            except: pass
        await self._send(chat_id, f"Broadcast sent to {count} users.")

    async def _send(self, chat_id, text, keyboard=None, use_signal_bot=False):
        payload = {"chat_id": chat_id, "text": self._repair_mojibake_text(text), "parse_mode": "HTML"}
        if keyboard: payload["reply_markup"] = keyboard
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
        except: pass

    async def _delete_message(self, chat_id, message_id):
        try:
            async with self.session.post(f"{self.base_url}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=5) as resp:
                await resp.text()
        except: pass

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
                f"<b>RAM Used:</b> <code>{ram}%</code>\n"
                f"<b>Last Backup:</b> <code>{last_bk}</code>\n"
                f"------------------------------\n"
                f"<i>IST: {ist_now}</i>"
            )
            await self._send(chat_id, msg)
        except Exception as e:
            logger.error(f"Pulse failed: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(AdminPanel().run())
    except KeyboardInterrupt:
        pass

