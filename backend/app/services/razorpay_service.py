"""Razorpay client built per-instance from a PaymentProviderConfig.

This is no longer a singleton. The PaymentRegistry hands out RazorpayProvider
instances for the currently-active config. Hot-swapping a key (or switching
between test/live) is a one-line admin API call.
"""
import hmac
import hashlib


class RazorpayProvider:
    name = "razorpay"

    def __init__(self, key_id: str, key_secret: str,
                 webhook_secret: str | None = None,
                 mode: str = "test", **config):
        try:
            import razorpay
        except ImportError as e:
            # ImportError covers both the SDK being absent AND any of its
            # transitive deps failing to import (e.g. setuptools >=80
            # broke razorpay 1.x's `import pkg_resources`). Surface the
            # real exception so the admin's "Test" button doesn't lie.
            raise RuntimeError(
                f"Razorpay SDK failed to load: {type(e).__name__}: {e}. "
                "Rebuild the backend image (deploy.sh runs `compose build "
                "--pull` automatically); if it persists, check that "
                "requirements.txt's setuptools pin is intact."
            ) from e
        self.client = razorpay.Client(auth=(key_id, key_secret))
        self.key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self.mode = mode
        self.config = config

    def create_order(self, amount_paise: int,
                     receipt: str | None = None,
                     currency: str = "INR") -> dict:
        return self.client.order.create({
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "payment_capture": 1,
        })

    def verify_payment_signature(self, order_id: str,
                                 payment_id: str, signature: str) -> bool:
        body = f"{order_id}|{payment_id}".encode()
        expected = hmac.new(self._key_secret.encode(), body,
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            return False
        expected = hmac.new(self._webhook_secret.encode(), payload,
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def smoke_test(self) -> dict:
        """Lightweight connectivity check — fetches account/payment list of size 1."""
        try:
            self.client.payment.all({"count": 1})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
