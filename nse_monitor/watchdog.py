import time
import threading
import logging
import requests
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class BotWatchdog:
    """v16.0: Monitors bot health and auto-reports logs if a hang is detected."""
    
    def __init__(self, admin_chat_id, bot_token, log_path):
        self.admin_chat_id = admin_chat_id
        self.bot_token = bot_token
        self.log_path = log_path
        self.last_heartbeat = time.time()
        self.is_running = False
        self.alert_sent = False
        self.monitor_thread = None

    def heartbeat(self):
        """Called by the main loop to signal the bot is alive."""
        self.last_heartbeat = time.time()
        if self.alert_sent:
            self._send_admin_msg("✅ <b>SYSTEM RECOVERED:</b> Heartbeat restored. Monitoring active.")
            self.alert_sent = False

    def start(self):
        """Starts the background watchdog thread."""
        if self.is_running: return
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Bot Watchdog (Heartbeat Monitor) Active.")

    def _monitor_loop(self):
        while self.is_running:
            try:
                time.sleep(60) # Check every minute
                idle_time = time.time() - self.last_heartbeat
                
                # If idle for more than 5 minutes (300 seconds)
                if idle_time > 300 and not self.alert_sent:
                    logger.critical(f"WATCHDOG ALERT: Bot hung for {int(idle_time)}s. Sending logs to Admin.")
                    self._report_failure(int(idle_time))
                    self.alert_sent = True
                    
            except Exception as e:
                logger.error(f"Watchdog Loop Error: {e}")

    def _report_failure(self, idle_time):
        """Reads last 100 logs and sends to Admin."""
        logs = self._get_last_logs(100)
        msg = (
            f"🚨 <b>SYSTEM HANG DETECTED</b>\n"
            f"────────────────────────\n"
            f"<b>Idle Time:</b> {idle_time} seconds\n"
            f"<b>Status:</b> No loop execution detected since {datetime.fromtimestamp(self.last_heartbeat).strftime('%H:%M:%S')}\n"
            f"────────────────────────\n"
            f"📝 <b>LAST 100 LOG LINES:</b>\n"
            f"<pre>{logs}</pre>"
        )
        self._send_admin_msg(msg)

    def _get_last_logs(self, n=100):
        """Safely reads the last n lines of the service log."""
        if not os.path.exists(self.log_path):
            return "Log file not found."
            
        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Efficient way to get last n lines
                lines = f.readlines()
                return "".join(lines[-n:])
        except Exception as e:
            return f"Error reading logs: {e}"

    def _send_admin_msg(self, text):
        """Direct Telegram API call to bypass any bot-level thread locks."""
        if not self.admin_chat_id or not self.bot_token: return
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.admin_chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Watchdog Telegram Notify Failed: {e}")

    def stop(self):
        self.is_running = False
