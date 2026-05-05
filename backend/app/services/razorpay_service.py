"""Razorpay client wrapper with order creation + signature verification."""
import hmac
import hashlib
import razorpay
from app.core.config import settings


class RazorpayService:
    def __init__(self):
        self.client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        ) if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET else None

    def create_order(self, amount_paise: int, receipt: str | None = None,
                     currency: str = "INR") -> dict:
        if not self.client:
            raise RuntimeError("Razorpay not configured (set RAZORPAY_KEY_ID/SECRET)")
        return self.client.order.create({
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "payment_capture": 1,
        })

    def verify_payment_signature(self, order_id: str, payment_id: str,
                                 signature: str) -> bool:
        body = f"{order_id}|{payment_id}".encode()
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            return False
        expected = hmac.new(
            settings.RAZORPAY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


razorpay_service = RazorpayService()
