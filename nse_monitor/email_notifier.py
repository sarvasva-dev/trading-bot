import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
try:
    from nse_monitor.config import ALERT_EMAILS, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
except ImportError:
    ALERT_EMAILS, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS = [], None, 587, None, None

logger = logging.getLogger(__name__)

class EmailNotifier:
    def __init__(self):
        self.emails = ALERT_EMAILS
        self.host = SMTP_HOST
        self.port = SMTP_PORT
        self.user = SMTP_USER
        self.password = SMTP_PASS

    def send_failure_alert(self, subject, error_message):
        """Sends a critical failure alert to the configured admin emails."""
        if not self.emails or not self.host or not self.user or not self.password:
            logger.warning("SMTP Config missing. Cannot send failure email.")
            return

        for email_address in self.emails:
            try:
                msg = MIMEMultipart()
                msg['From'] = self.user
                msg['To'] = email_address
                msg['Subject'] = f"🚨 ERROR: {subject}"

                body = (
                    f"Market Intelligence Bot has encountered a critical issue:\n\n"
                    f"Error Details:\n{error_message}\n\n"
                    f"Please check your server logs immediately."
                )
                msg.attach(MIMEText(body, 'plain'))

                server = smtplib.SMTP(self.host, self.port)
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)
                server.quit()
                logger.info(f"Failure email sent to {email_address}")
            except Exception as e:
                logger.error(f"Failed to send email alert to {email_address}: {e}")
