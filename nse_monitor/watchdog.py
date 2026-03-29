import time
import threading
import logging
import requests
import os
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


class BotWatchdog:
    """
    v1.0: Self-Healing Watchdog.
    - Monitors bot heartbeat every 60 seconds.
    - If idle > 5 minutes: sends logs to Admin AND triggers a controlled restart.
    """

    HANG_THRESHOLD_SECONDS = 300   # 5 minutes
    CHECK_INTERVAL_SECONDS = 60    # Check every 1 minute

    def __init__(self, notifier, log_path):
        self.notifier = notifier
        self.log_path = log_path
        self.last_heartbeat = time.time()
        self.is_running = False
        self.alert_sent = False
        self.monitor_thread = None

    def heartbeat(self):
        """Called by main loop every cycle to signal the bot is alive."""
        self.last_heartbeat = time.time()
        if self.alert_sent:
            # v1.3: Centralized messaging
            self._send_admin_msg(
                "✅ <b>SYSTEM RECOVERED</b>\n"
                "────────────────────────\n"
                "Heartbeat restored. Intelligence cycle is back online."
            )
            self.alert_sent = False

    def start(self):
        """Starts the background watchdog monitor thread."""
        if self.is_running:
            return
        self.is_running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True
        )
        self.monitor_thread.start()
        logger.info("🐕 Self-Healing Watchdog: Active (5-min timeout).")

    def _monitor_loop(self):
        while self.is_running:
            try:
                time.sleep(self.CHECK_INTERVAL_SECONDS)
                idle_time = time.time() - self.last_heartbeat

                if idle_time > self.HANG_THRESHOLD_SECONDS and not self.alert_sent:
                    logger.critical(
                        f"🚨 WATCHDOG: Bot hung for {int(idle_time)}s. "
                        f"Reporting & triggering restart..."
                    )
                    self._report_failure(int(idle_time))
                    self.alert_sent = True

                    # v1.0: Self-healing restart
                    # Give 5 seconds for the admin message to send
                    time.sleep(5)
                    self._trigger_restart()

            except Exception as e:
                logger.error(f"Watchdog Loop Error: {e}")

    def _report_failure(self, idle_time):
        """Sends the last 100 log lines to Admin before restarting."""
        logs = self._get_last_logs(100)
        msg = (
            f"🚨 <b>SYSTEM HANG DETECTED</b>\n"
            f"────────────────────────\n"
            f"<b>Idle Time:</b> {idle_time} seconds\n"
            f"<b>Last Heartbeat:</b> {datetime.fromtimestamp(self.last_heartbeat).strftime('%d %b %H:%M:%S')}\n"
            f"<b>Action:</b> Auto-restart triggered.\n"
            f"────────────────────────\n"
            f"📝 <b>LAST LOG LINES:</b>\n"
            f"<pre>{logs[-3000:]}</pre>"  # Telegram message limit safe
        )
        self._send_admin_msg(msg)

    def _trigger_restart(self):
        """
        v1.0: Self-healing restart.
        Exits the process cleanly. The run_all.bat / systemd service
        will automatically restart the bot.
        """
        logger.critical("🔄 WATCHDOG: Triggering controlled restart via sys.exit(0)...")
        self._send_admin_msg(
            "🔄 <b>Auto-Restart Initiated</b>\n"
            "Bot is restarting now. Service should be back in ~15 seconds."
        )
        time.sleep(2)
        os._exit(0)   # Hard exit — bypasses threading cleanup to ensure restart

    def _get_last_logs(self, n=100):
        """Safely reads the last n lines of the service log."""
        if not os.path.exists(self.log_path):
            # Try the app.log fallback
            alt_path = os.path.join(os.path.dirname(self.log_path), "app.log")
            if os.path.exists(alt_path):
                self.log_path = alt_path
            else:
                return "Log file not found."
        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                return "".join(lines[-n:])
        except Exception as e:
            return f"Error reading logs: {e}"

    def _send_admin_msg(self, text):
        """Uses the centralized notifier for admin messages."""
        self.notifier.send_status_update(text)

    def stop(self):
        self.is_running = False
