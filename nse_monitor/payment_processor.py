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

    def create_payment_link(self, chat_id, plan_type, first_name="User"):
        """Generates a Razorpay Payment Link for a specific plan."""
        if not self.client: return None
        
        # RULE #24: Safe dynamic plan fetch
        plan = SUBSCRIPTION_PLANS.get(str(plan_type))
        if not plan: 
            logger.error(f"Invalid plan type requested: {plan_type}")
            return None
        
        try:
            payload = {
                "amount": plan["amount"] * 100,
                "currency": "INR",
                "accept_partial": False,
                "first_min_partial_amount": 0,
                "expire_by": int((datetime.now() + timedelta(days=1)).timestamp()),
                "reference_id": f"SUB_{chat_id}_{plan_type}_{int(datetime.now().timestamp())}",
                "description": f"Market Pulse {plan['label']} Access",
                "customer": {"name": first_name, "contact": "", "email": ""},
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
                "notes": {
                    "chat_id": str(chat_id),
                    "plan_days": str(plan["days"])
                },
                "callback_url": "",
                "callback_method": "get"
            }
            
            pl = self.client.payment_link.create(payload)
            return {
                "id": pl["id"],
                "short_url": pl["short_url"],
                "days": plan["days"]
            }
        except Exception as e:
            logger.error(f"Error creating Razorpay link: {e}")
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
