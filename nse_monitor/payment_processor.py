try:
    import razorpay
except ImportError:
    razorpay = None
import logging
from datetime import datetime, timedelta
from nse_monitor.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, SUBSCRIPTION_PLANS

logger = logging.getLogger(__name__)

class RazorpayProcessor:
    def __init__(self):
        self.client = None
        if razorpay:
            try:
                self.client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
                logger.info("Razorpay Client Initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Razorpay Client: {e}")
        else:
            logger.warning("Razorpay library not found. Payment features will be disabled (Rule #24).")

    def create_payment_link(self, chat_id, amount_str, first_name="User", days=None, label=None):
        """Generates a Razorpay Payment Link for a given amount.
        amount_str: the actual payable amount (may differ from plan price after discount).
        days/label: optional override; if omitted, looked up from SUBSCRIPTION_PLANS by amount.
        """
        if not self.client: return None

        try:
            amount = int(amount_str)
        except (ValueError, TypeError):
            logger.error(f"Invalid amount: {amount_str}")
            return None

        # Look up plan metadata by amount if not provided
        if days is None or label is None:
            plan = SUBSCRIPTION_PLANS.get(str(amount))
            if plan:
                days = days or plan["days"]
                label = label or plan["label"]
            else:
                # Discounted amount — find closest plan by days already stored
                days = days or 0
                label = label or "Subscription"

        try:
            payload = {
                "amount": amount * 100,
                "currency": "INR",
                "accept_partial": False,
                "first_min_partial_amount": 0,
                "expire_by": int((datetime.now() + timedelta(days=1)).timestamp()),
                "reference_id": f"SUB_{chat_id}_{amount}_{int(datetime.now().timestamp())}",
                "description": f"Bulkbeat TV {label} Access",
                "customer": {"name": first_name, "contact": "", "email": ""},
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
                "notes": {
                    "chat_id": str(chat_id),
                    "plan_days": str(days)
                },
                "callback_url": "",
                "callback_method": "get"
            }

            logger.info(f"Generating Razorpay Link for {chat_id} | Amount: {amount} | Days: {days}")
            pl = self.client.payment_link.create(payload)
            logger.info(f"✅ Success: Razorpay Link Generated: {pl['id']}")
            return {
                "id": pl["id"],
                "short_url": pl["short_url"],
                "days": days
            }
        except Exception as e:
            logger.error(f"❌ Error creating Razorpay link: {e}", exc_info=True)
            return None

    def verify_payment_status(self, pl_id):
        """Checks if a payment link has been paid successfully and returns credits."""
        if not self.client: return None
        
        try:
            pl = self.client.payment_link.fetch(pl_id)
            if pl["status"] == "paid":
                # Extract days from notes
                return int(pl.get("notes", {}).get("plan_days", 0))
            return None
        except Exception as e:
            logger.error(f"Error fetching Razorpay link status: {e}")
            return None
