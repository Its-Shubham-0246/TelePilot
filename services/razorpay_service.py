import logging
import razorpay
from typing import Dict, Any, Optional
from config import settings

logger = logging.getLogger(__name__)


class RazorpayService:
    def __init__(self):
        self._client: Optional[razorpay.Client] = None

    @property
    def client(self) -> razorpay.Client:
        if self._client is None:
            if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
                raise ValueError("Razorpay Key ID and Key Secret must be set in environment / settings.")
            self._client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
        return self._client

    def create_payment_link(
        self,
        user_id: int,
        days: int,
        amount_inr: int,
        plan_name: str,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        user_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay Payment Link for subscription purchase.
        Amount is automatically converted from INR to paise (x 100).
        """
        payload = {
            "amount": amount_inr * 100,  # Amount in paise
            "currency": "INR",
            "accept_partial": False,
            "description": f"Subscription: {plan_name}",
            "customer": {
                "name": user_name or f"Telegram User {user_id}",
                "email": user_email or f"user_{user_id}@telegram.bot",
                "contact": user_phone or "+910000000000"
            },
            "notify": {
                "sms": False,
                "email": False
            },
            "reminder_enable": True,
            "notes": {
                "telegram_user_id": str(user_id),
                "plan_days": str(days),
                "plan_name": plan_name
            }
        }
        
        try:
            link_response = self.client.payment_link.create(payload)
            logger.info(f"Created Razorpay payment link {link_response.get('id')} for user {user_id}")
            return link_response
        except Exception as e:
            logger.error(f"Failed to create Razorpay payment link for user {user_id}: {e}")
            raise e

    def verify_webhook_signature(self, body_bytes: bytes, signature: str) -> bool:
        """Verifies incoming Razorpay Webhook signature."""
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            logger.warning("RAZORPAY_WEBHOOK_SECRET is not configured.")
            return False
        try:
            self.client.utility.verify_webhook_signature(
                body_bytes.decode('utf-8'),
                signature,
                settings.RAZORPAY_WEBHOOK_SECRET
            )
            return True
        except razorpay.errors.SignatureVerificationError:
            logger.error("Razorpay webhook signature verification failed.")
            return False


razorpay_service = RazorpayService()
