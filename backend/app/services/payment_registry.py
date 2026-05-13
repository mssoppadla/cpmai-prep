"""Dynamic payment provider registry.

Loads the active PaymentProviderConfig from DB, decrypts secrets, and
caches the built provider with TTL. Same shape as LLMRegistry — admin
changes propagate within ~30s with no restart.

Currency routing
----------------
Two routes are supported and configured independently in admin:

  * INR (and the default) → ``payment.active_provider_id``
    (typically Razorpay; the historical path, kept unchanged so the
    Indian-customer flow is untouched by the international work).

  * Non-INR → ``payment.non_inr_provider_id`` (typically PayPal).
    If unset, /orders for non-INR raises a clear error pointing the
    admin at /admin/payment-providers — we don't fall through to the
    INR provider silently because Razorpay International requires its
    own approval gate that we can't auto-detect.

The cache keys on provider_id so both routes can be hot at once; an
admin swapping a key propagates within payment.cache_ttl_seconds
(default 30) without a restart.
"""
import time
from threading import Lock
from app.core.database import SessionLocal
from app.core.settings_store import settings_store
from app.core.crypto import crypto
from app.core.exceptions import AppError
from app.models.payment_provider import PaymentProviderConfig
from app.services.razorpay_service import RazorpayProvider
from app.services.paypal_service import PayPalProvider


PROVIDER_CLASSES = {
    "razorpay": RazorpayProvider,
    "paypal":   PayPalProvider,
    # "stripe": StripeProvider,  # add when needed
}


class _CacheEntry:
    __slots__ = ("provider", "expires_at", "config_id")

    def __init__(self, provider, expires_at, config_id):
        self.provider = provider
        self.expires_at = expires_at
        self.config_id = config_id


class PaymentRegistry:
    # Two slots so INR and non-INR providers can both live hot. Keyed
    # by provider_id (NOT currency) so the cache is correct even when
    # admin renumbers the routing.
    _cache: dict[int, _CacheEntry] = {}
    _lock = Lock()

    @classmethod
    def get_active(cls):
        """Backward-compat: returns the INR provider (the historical
        single-provider behaviour). New code should use
        ``get_for_currency()`` instead so non-INR is routed correctly.
        """
        active_id = settings_store.get("payment.active_provider_id")
        if active_id is None:
            raise AppError("Payments not configured. Add a payment provider in admin.",
                           status_code=503)
        return cls._get(int(active_id))

    @classmethod
    def get_for_currency(cls, currency: str):
        """Pick the provider for a given ISO-4217 currency.

        INR (and missing/empty currency) → active_provider_id (Razorpay).
        Anything else → non_inr_provider_id (PayPal), with a clear error
        if it isn't configured yet.
        """
        ccy = (currency or "INR").strip().upper()
        if ccy == "INR":
            return cls.get_active()
        non_inr_id = settings_store.get("payment.non_inr_provider_id")
        if not non_inr_id:
            raise AppError(
                f"No non-INR payment provider configured. Add one in "
                f"/admin/payment-providers and set it as the 'Non-INR' "
                f"provider, then retry. Requested currency: {ccy}.",
                status_code=503)
        return cls._get(int(non_inr_id))

    @classmethod
    def get_by_id(cls, provider_id: int):
        return cls._get(provider_id)

    @classmethod
    def invalidate(cls):
        with cls._lock:
            cls._cache.clear()

    @classmethod
    def _get(cls, provider_id: int):
        ttl = settings_store.get_int("payment.cache_ttl_seconds", 30)
        now = time.monotonic()
        with cls._lock:
            entry = cls._cache.get(provider_id)
            if entry and entry.expires_at > now:
                return entry.provider

        with SessionLocal() as db:
            row = db.get(PaymentProviderConfig, provider_id)
            if not row or not row.is_enabled:
                raise AppError(f"Payment provider {provider_id} not available.",
                               status_code=503)
            cls_ = PROVIDER_CLASSES.get(row.provider_type)
            if not cls_:
                raise AppError(f"Unknown payment provider_type: {row.provider_type}",
                               status_code=500)
            if not crypto:
                raise AppError("ENCRYPTION_KEY not configured.", status_code=500)

            api_secret = (crypto.decrypt(row.api_secret_encrypted)
                          if row.api_secret_encrypted else None)
            webhook_secret = (crypto.decrypt(row.webhook_secret_encrypted)
                              if row.webhook_secret_encrypted else None)
            if not row.public_key or not api_secret:
                raise AppError("Active payment provider is missing credentials.",
                               status_code=503)

            provider = cls_(
                key_id=row.public_key, key_secret=api_secret,
                webhook_secret=webhook_secret, mode=row.mode,
                **(row.config or {}),
            )

        with cls._lock:
            cls._cache[provider_id] = _CacheEntry(provider, now + ttl, provider_id)
        return provider
