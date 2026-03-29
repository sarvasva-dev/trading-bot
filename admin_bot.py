import logging
import requests
import time
import os
import json
import html
import psutil
import shutil
from datetime import datetime
import pytz
from nse_monitor.config import TELEGRAM_ADMIN_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID, ADMIN_PASSWORD, BOT_NAME, TELEGRAM_BOT_TOKEN
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
        self.sessions_file = os.path.join("data", "admin_sessions.json")
        
        self.db = Database()
        self.last_update_id = 0
        self.authenticated_sessions = self._load_sessions() # chat_id: timestamp
        self._set_latest_offset()

    def _set_latest_offset(self):
        """Skip all stale messages on startup (Rule #24)."""
        try:
            r = requests.get(f"{self.base_url}/getUpdates", params={"offset": -1, "limit": 1}, timeout=5)
            data = r.json()
            if data.get("ok") and data.get("result"):
                self.last_update_id = data["result"][0]["update_id"]
                logger.info(f"Admin Bot Offset Synced: {self.last_update_id}")
        except: pass

    def is_admin(self, chat_id):
        cid = str(chat_id)
        # 1. Owner bypass
        if cid == self.owner_id: return True
        # 2. Session check (60 mins)
        session_time = self.authenticated_sessions.get(cid, 0)
        return (time.time() - session_time) < 3600

    def run(self):
        logger.info(f"--- {BOT_NAME} ADMIN PANEL ONLINE ---")
        if self.owner_id:
            logger.info(f"Owner Auto-Login: {self.owner_id}")
        
        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self.last_update_id = update["update_id"]
                    if "message" in update:
                        self._handle_message(update["message"])
                    elif "callback_query" in update:
                        self._handle_callback(update["callback_query"])
                time.sleep(1)
            except Exception as e:
                logger.error(f"Admin Main Loop Error: {e}")
                time.sleep(5)

    def _get_updates(self):
        url = f"{self.base_url}/getUpdates"
        params = {"offset": self.last_update_id + 1, "timeout": 20}
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        return data.get("result", []) if data.get("ok") else []

    def _handle_message(self, msg):
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        
        # 1. Login Logic
        if text.startswith("/login"):
            parts = text.split()
            if len(parts) == 2 and parts[1] == ADMIN_PASSWORD:
                self.authenticated_sessions[chat_id] = time.time()
                self._save_sessions() # v1.3 Persistence
                self._send(chat_id, "🔓 <b>Authentication Successful!</b>\nYou now have persistent admin access.")
                self._send_main_menu(chat_id)
            else:
                self._send(chat_id, "🚫 <b>Invalid Credentials.</b>")
            return

        # 2. Admin Command Guard
        if not self.is_admin(chat_id):
            self._send(chat_id, "🔒 <b>Access Denied.</b>\nPlease use <code>/login <password></code>")
            return

        # 3. Command Router
        if text == "/start" or text == "/admin":
            self._send_main_menu(chat_id)
        elif text == "/status":
            self._handle_status(chat_id)
        elif text == "/pulse":
            self._handle_pulse(chat_id)
        elif text == "/users":
            self._handle_users(chat_id)
        elif text.startswith("/find"):
            self._handle_find(chat_id, text)
        elif text.startswith("/grant"):
            self._handle_grant(chat_id, text)
        elif text.startswith("/broadcast"):
            self._handle_broadcast(chat_id, text)

    def _handle_callback(self, cb):
        from_id = str(cb["from"]["id"])
        chat_id = from_id # Private chat context
        data = cb["data"]
        
        if not self.is_admin(from_id):
            self._answer_callback(cb["id"], "Session Expired! Please login.")
            return

        if data == "menu_status":
            self._handle_status(chat_id)
        elif data == "menu_list" or data == "menu_users":
            self._handle_list(chat_id, 0)
        elif data == "menu_broadcast":
            self._send(chat_id, "📢 Usage: <code>/broadcast &lt;message&gt;</code>\nThis will notify ALL active subscribers.")
        elif data == "menu_config":
            self._show_config_menu(chat_id)
        elif data == "menu_hisab":
            self._handle_global_hisab(chat_id)
        elif data == "menu_rescue":
            self._handle_system_rescue(chat_id)
        elif data.startswith("set_threshold_"):
            val = data.split("_")[2]
            self.db.set_config("ai_threshold", val)
            self._answer_callback(cb["id"], f"✅ AI Threshold set to {val}", show_alert=True)
            self._show_config_menu(chat_id)
        elif data == "toggle_media_mute":
            current = self.db.get_config("media_mute", "0")
            new_val = "1" if current == "0" else "0"
            self.db.set_config("media_mute", new_val)
            self._answer_callback(cb["id"], f"✅ Media Mute: {'ON' if new_val == '1' else 'OFF'}", show_alert=True)
            self._show_config_menu(chat_id)
        elif data.startswith("list_page_"):
            page = int(data.split("_")[2])
            offset = page * 10
            self._handle_list(chat_id, offset)
        elif data.startswith("manage_"):
            uid = data.split("_")[1]
            self._show_manage_menu(chat_id, uid)
        elif data.startswith("reset_"):
            uid = data.split("_")[1]
            self._execute_reset(chat_id, uid)
        elif data.startswith("deactivate_"):
            uid = data.split("_")[1]
            self._execute_deactivate(chat_id, uid)
        elif data.startswith("plans_"):
            uid = data.split("_")[1]
            self._show_plan_options(chat_id, uid)
        elif data.startswith("grant_"):
            _, uid, days = data.split("_")
            self._execute_grant_interactive(chat_id, uid, int(days))
        
        elif data == "menu_main":
            self._send_main_menu(chat_id)
        elif data == "action_vacuum":
            try:
                self.db.conn.execute("VACUUM")
                self._answer_callback(cb["id"], "✅ Database Vacuum Complete!", show_alert=True)
            except Exception as e:
                self._answer_callback(cb["id"], f"❌ Error: {e}", show_alert=True)
        elif data == "action_purge":
            try:
                deleted = self.db.purge_old_data(days=30)
                self._answer_callback(cb["id"], f"✅ Purge Complete: {deleted} items removed.", show_alert=True)
            except Exception as e:
                self._answer_callback(cb["id"], f"❌ Purge Failed: {e}", show_alert=True)
        elif data == "action_sync_holidays":
            from nse_monitor.trading_calendar import TradingCalendar
            success = TradingCalendar.sync_from_nse()
            if success:
                self._answer_callback(cb["id"], "✅ NSE Holidays Synced Successfully!", show_alert=True)
            else:
                self._answer_callback(cb["id"], "❌ Sync Failed. Check logs.", show_alert=True)
        
        self._answer_callback(cb["id"])

    def _send_main_menu(self, chat_id):
        text = (
            f"🛠️ <b>{BOT_NAME} ADMIN GUIDE (v11.0)</b>\n"
            f"────────────────────────\n"
            f"<b>Commands:</b>\n"
            f"• <code>/list</code> — Full User Audit Log\n"
            f"• <code>/grant &lt;id&gt; &lt;days&gt;</code> — Manual Credit\n"
            f"• <code>/broadcast &lt;msg&gt;</code> — Global Alert\n"
            f"• <code>/status</code> — System Health Check\n\n"
            f"<b>Key Indicators:</b>\n"
            f"💎 = Active Premium | 🆓 = Free/Trial\n\n"
            f"Select an action below for quick access:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 System Status", "callback_data": "menu_status"}, {"text": "⚙️ Bot Config", "callback_data": "menu_config"}],
                [{"text": "📋 User Audit", "callback_data": "menu_list"}, {"text": "📈 Global Hisab", "callback_data": "menu_hisab"}],
                [{"text": "📢 Broadcast", "callback_data": "menu_broadcast"}, {"text": "🆘 DB Rescue", "callback_data": "menu_rescue"}]
            ]
        }
        self._send(chat_id, text, keyboard)

    def _show_config_menu(self, chat_id):
        thresh = self.db.get_config("ai_threshold", "5")
        mute = self.db.get_config("media_mute", "0")
        
        mute_label = "🔇 UNMUTE Media" if mute == "1" else "🔈 MUTE Media"
        
        text = (
            f"⚙️ <b>BOT LIVE CONFIG</b>\n"
            f"────────────────────────\n"
            f"🎯 <b>Current Threshold:</b> {thresh}/10\n"
            f"📢 <b>Media Source:</b> {'MUTED (Official Only)' if mute == '1' else 'ACTIVE'}\n"
            f"────────────────────────\n"
            f"<i>Changes apply instantly to the next cycle.</i>"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🎯 Threshold: 3 (Aggressive)", "callback_data": "set_threshold_3"}],
                [{"text": "🎯 Threshold: 5 (Standard)", "callback_data": "set_threshold_5"}],
                [{"text": "🎯 Threshold: 7 (Safe)", "callback_data": "set_threshold_7"}],
                [{"text": mute_label, "callback_data": "toggle_media_mute"}],
                [{"text": "🔙 Back to Main Menu", "callback_data": "menu_main"}]
            ]
        }
        self._send(chat_id, text, keyboard)

    def _handle_global_hisab(self, chat_id):
        """v2.0: Industrial Audit of all system credit movements."""
        debits, users = self.db.get_global_hisab(days=1)
        debits_week, users_week = self.db.get_global_hisab(days=7)
        
        text = (
            f"📈 <b>GLOBAL AUDIT (HISAB)</b>\n"
            f"────────────────────────\n"
            f"<b>Today's Volume:</b>\n"
            f"💳 Deducted: <b>{debits} Market Days</b>\n"
            f"👥 Unique Users: {users}\n\n"
            f"<b>Last 7 Days:</b>\n"
            f"💳 Total Debits: {debits_week}\n"
            f"👥 Unique Reach: {users_week}\n"
            f"────────────────────────\n"
            f"📍 <i>Internal Finance Audit Only</i>"
        )
        self._send(chat_id, text)

    def _handle_system_rescue(self, chat_id):
        """Allows manual DB maintenance from Telegram."""
        text = (
            "🆘 <b>SYSTEM RESCUE & MAINTENANCE</b>\n"
            "────────────────────────\n"
            "⚠️ <b>WARNING:</b> These actions are destructive or performance intensive.\n\n"
            "<b>1. Repair DB:</b> Runs VACUUM to fix minor corruption.\n"
            "<b>2. Update Holidays:</b> Live Sync from NSE server.\n"
            "<b>3. Purge Engine:</b> Deletes news older than 30 days.\n"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🛠️ Run DB Vacuum", "callback_data": "action_vacuum"}],
                [{"text": "🗓️ Sync NSE Holidays", "callback_data": "action_sync_holidays"}],
                [{"text": "🧹 Purge Old News", "callback_data": "action_purge"}],
                [{"text": "🔙 Back", "callback_data": "menu_main"}]
            ]
        }
        self._send(chat_id, text, keyboard)

    def _handle_status(self, chat_id):
        total, active = self.db.get_user_stats()
        text = (
            f"📊 <b>PRODUCTION STATUS (v11.0)</b>\n"
            f"────────────────────────\n"
            f"✅ <b>Signal Engine:</b> ACTIVE\n"
            f"🧠 <b>AI Processor:</b> ONLINE\n\n"
            f"👥 <b>Total Users:</b> {total}\n"
            f"⚡ <b>Active Subs:</b> {active}\n"
            f"────────────────────────\n"
            f"📍 <i>Build: Institutional Prime</i>"
        )
        self._send(chat_id, text)

    def _handle_list(self, chat_id, offset=0):
        """Highly detailed user audit list with pagination (v12.0)."""
        limit = 10
        users = self.db.get_all_users(limit=limit, offset=offset)
        page = offset // limit
        
        text = f"📋 <b>USER AUDIT (Page {page + 1})</b>\n────────────────────────\n"
        keyboard = {"inline_keyboard": []}
        
        for u in users:
            uid, name, uname, active, days = u
            has_username = uname and uname not in ("manual_entry", "Unknown", "Legacy", "Sync_Legacy", "None")
            uname_label = f"@{uname}" if has_username else f"...{str(uid)[-6:]}"
            display_name = name if name and name != "Sync_Legacy" else "User"
            icon = "💎" if active else "🆓"
            text += f"{icon} {display_name} {uname_label} [<code>{uid}</code>] | <b>{days}d</b>\n"
            keyboard["inline_keyboard"].append([{"text": f"⚙️ {uname_label}", "callback_data": f"manage_{uid}"}])
        
        # Pagination Buttons
        nav_buttons = []
        if offset > 0:
            nav_buttons.append({"text": "⬅️ Prev", "callback_data": f"list_page_{page - 1}"})
        if len(users) == limit:
            nav_buttons.append({"text": "Next ➡️", "callback_data": f"list_page_{page + 1}"})
        
        if nav_buttons:
            keyboard["inline_keyboard"].append(nav_buttons)
            
        if not users:
            text += "<i>No more users found.</i>"
            
        text += "────────────────────────\n"
        text += "💡 <i>Click user for Manage Menu.</i>"
        self._send(chat_id, text, keyboard)

    def _show_manage_menu(self, chat_id, uid):
        user = self.db.get_user(uid)
        if not user: return
        
        name = user[1]
        text = (
            f"⚙️ <b>MANAGE USER:</b> {name}\n"
            f"🆔 <b>ID:</b> <code>{uid}</code>\n"
            f"⏳ <b>Current Balance:</b> {user[4]} days\n"
            f"────────────────────────\n"
            f"Select an action to perform:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 Reset to 0 Days", "callback_data": f"reset_{uid}"}],
                [{"text": "🚫 Deactivate Account", "callback_data": f"deactivate_{uid}"}],
                [{"text": "➕ Add Plan (Grant Days)", "callback_data": f"plans_{uid}"}],
                [{"text": "🔙 Back to List", "callback_data": "menu_list"}]
            ]
        }
        self._send(chat_id, text, keyboard)

    def _show_plan_options(self, chat_id, uid):
        text = f"➕ <b>SELECT PLAN TO GRANT:</b>\nGrant days to user <code>{uid}</code> instantly."
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔸 Star Plan (+2d)", "callback_data": f"grant_{uid}_2"}],
                [{"text": "🔹 Growth Plan (+7d)", "callback_data": f"grant_{uid}_7"}],
                [{"text": "🚀 Professional (+28d)", "callback_data": f"grant_{uid}_28"}],
                [{"text": "🏆 Institutional (+336d)", "callback_data": f"grant_{uid}_336"}],
                [{"text": "🔙 Back", "callback_data": f"manage_{uid}"}]
            ]
        }
        self._send(chat_id, text, keyboard)

    def _execute_deactivate(self, chat_id, uid):
        self.db.toggle_user_status(uid, 0)
        self._send(chat_id, f"🚫 <b>Action Complete:</b> User <code>{uid}</code> has been deactivated. Signals paused.")
        self._show_manage_menu(chat_id, uid)

    def _execute_reset(self, chat_id, uid):
        self.db.reset_user_days(uid)
        self._send(chat_id, f"✅ <b>Action Complete:</b> User <code>{uid}</code> balance reset to 0.")
        # Optional: Notify user? Or just keep it silent.
        self._show_manage_menu(chat_id, uid)

    def _execute_grant_interactive(self, chat_id, uid, days):
        self.db.add_working_days(uid, days)
        self.db.toggle_user_status(uid, 1)
        self._send(chat_id, f"✅ <b>Success:</b> Granted {days} days to <code>{uid}</code>.")
        
        # 🔔 Notify Target User via Signal Bot
        msg = (
            f"🎁 <b>Manual Account Activation!</b>\n"
            f"────────────────────────\n"
            f"The Administrator has credited your account with <b>{days} Market Days</b>.\n\n"
            f"Your professional intelligence engine is now <b>LIVE</b> and scanning for NSE signals. 📈"
        )
        self._notify_user_via_signal_bot(uid, msg)
        self._show_manage_menu(chat_id, uid)

    def _handle_find(self, chat_id, text):
        """Search users by ID or name (v12.0)."""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            self._send(chat_id, "🔍 Usage: <code>/find &lt;name or id&gt;</code>")
            return
        
        query = parts[1].strip()
        results = self.db.search_users(query)
        
        if not results:
            self._send(chat_id, f"❌ No users found matching: <code>{query}</code>")
            return
        
        text_out = f"🔍 <b>Search Results for:</b> <code>{query}</code>\n────────────────────────\n"
        keyboard = {"inline_keyboard": []}
        for uid, name, uname, active, days in results:
            icon = "💎" if active else "🆓"
            text_out += f"{icon} {name} [<code>{uid}</code>] | {days}d\n"
            keyboard["inline_keyboard"].append([{"text": f"⚙️ Manage {name}", "callback_data": f"manage_{uid}"}])
        
        self._send(chat_id, text_out, keyboard)

    def _handle_users(self, chat_id):
        users = self.db.get_all_users(limit=15)
        text = "👥 <b>LATEST USERS (AUDIT)</b>\n────────────────────────\n"
        for u in users:
            uid, name, uname, active, days = u
            icon = "💎" if active else "🆓"
            text += f"{icon} {name} (<code>{uid}</code>) | {days}d\n"
        
        text += "\n💡 <i>To modify: /grant <id> <days></i>"
        self._send(chat_id, text)

    def _handle_grant(self, chat_id, text):
        parts = text.split()
        if len(parts) < 3:
            self._send(chat_id, "⚠️ Usage: <code>/grant <id> <days></code>")
            return
        
        target_id, days = parts[1], parts[2]
        self.db.add_working_days(target_id, int(days))
        self.db.toggle_user_status(target_id, 1)
        self._send(chat_id, f"✅ <b>Granted {days} days to {target_id}.</b> User is now ACTIVE.")
        
        # 🔔 Notify Target User via Signal Bot (Rule #24)
        msg = (
            f"🎁 <b>Manual Account Activation!</b>\n"
            f"────────────────────────\n"
            f"The Administrator has credited your account with <b>{days} Market Days</b>.\n\n"
            f"Your professional intelligence engine is now <b>LIVE</b> and scanning for NSE signals. 📈"
        )
        self._notify_user_via_signal_bot(target_id, msg)

    def _notify_user_via_signal_bot(self, user_id, text):
        """Cross-bot bridge for system notifications (Rule #24)."""
        payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        requests.post(f"{self.signal_bot_url}/sendMessage", json=payload, timeout=5)

    def _handle_broadcast(self, chat_id, text):
        msg_body = text.replace("/broadcast", "").strip()
        if not msg_body:
            self._send(chat_id, "⚠️ No message content provided.")
            return

        active_users = self.db.get_active_users()
        count = 0
        for uid in active_users:
            try:
                # v2.0: Always use Signal Bot for user broadcasts
                self._send(uid, f"📢 <b>ADMIN ANNOUNCEMENT</b>\n────────────────────────\n{msg_body}", use_signal_bot=True)
                count += 1
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"Broadcast failed for {uid}: {e}")
        
        self._send(chat_id, f"✅ <b>Broadcast complete.</b> Sent to {count} active users.")

    def _send(self, chat_id, text, keyboard=None, use_signal_bot=False):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if keyboard: payload["reply_markup"] = keyboard
        
        url = self.broadcast_url if use_signal_bot else f"{self.base_url}/sendMessage"
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Admin Bot: Failed to send msg to {chat_id}: {e}")

    def _answer_callback(self, cb_id, text=None, show_alert=False):
        payload = {"callback_query_id": cb_id}
        if text: 
            payload["text"] = text
            payload["show_alert"] = show_alert
        requests.post(f"{self.base_url}/answerCallbackQuery", json=payload, timeout=5)

    def _load_sessions(self):
        """v1.3: Loads admin sessions from JSON to survive restarts."""
        if os.path.exists(self.sessions_file):
            try:
                with open(self.sessions_file, "r") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_sessions(self):
        """v1.3: Persists admin sessions to disk."""
        os.makedirs("data", exist_ok=True)
        try:
            with open(self.sessions_file, "w") as f:
                json.dump(self.authenticated_sessions, f)
        except Exception as e:
            logger.error(f"Failed to save admin sessions: {e}")

    def _handle_pulse(self, chat_id):
        """v1.3.3: High-resolution system health & pulse monitoring."""
        self._send(chat_id, "🔍 <b>Fetching Industrial Pulse...</b>")
        
        # 1. Uptime calculation
        try:
            from nse_monitor.config import START_TIME
            uptime_sec = time.time() - START_TIME
        except:
            uptime_sec = 0
            
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        uptime_str = f"{int(days)}d {int(hours)}h {int(mins)}m"
        
        # 2. Disk & DB Size
        from nse_monitor.config import DB_PATH
        db_size_mb = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) / (1024 * 1024) or 0
        try:
            total, used, free = shutil.disk_usage("/")
            disk_used_pct = (used / total) * 100
        except: disk_used_pct = 0
        
        # 3. RAM Usage
        ram = psutil.virtual_memory()
        
        # 4. Last Backup
        last_bk = self.db.get_config("last_backup", "Never")
        if last_bk != "Never":
            try:
                last_bk = datetime.fromtimestamp(float(last_bk)).strftime("%d %b, %H:%M")
            except: pass
            
        msg = (
            f"🛰️ <b>{BOT_NAME} — INDUSTRIAL PULSE</b>\n"
            f"────────────────────────\n"
            f"📈 <b>Uptime:</b> <code>{uptime_str}</code>\n"
            f"🗄️ <b>DB Size:</b> <code>{db_size_mb:.2f} MB</code>\n"
            f"💾 <b>Disk Used:</b> <code>{disk_used_pct:.1f}%</code>\n"
            f"🧠 <b>RAM Used:</b> <code>{ram.percent}%</code>\n"
            f"🛡️ <b>Last Backup:</b> <code>{last_bk}</code>\n"
            f"────────────────────────\n"
            f"✅ <b>Status:</b> INSTITUTIONAL PRO\n"
            f"📍 <i>Server Time: {datetime.now().strftime('%H:%M:%S')}</i>"
        )
        
        self._send(chat_id, msg)

if __name__ == "__main__":
    AdminPanel().run()
