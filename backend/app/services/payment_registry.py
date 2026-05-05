"""Dynamic payment provider registry.

Loads the active PaymentProviderConfig from DB, decrypts secrets, and
caches the built provider with TTL. Same shape as LLMRegistry — admin
changes propagate within ~30s with no restart.
"""
import time
from threading import Lock
from app.core.database import SessionLocal
from app.core.settings_store import settings_store
from app.core.crypto import crypto
from app.core.exceptions import AppError
from app.models.payment_provider import PaymentProviderConfig
from app.services.razorpay_service import RazorpayProvider


PROVIDER_CLASSES = {
    "razorpay": RazorpayProvider,
    # "stripe": StripeProvider,  # add when needed
}


class _CacheEntry:
    __slots__ = ("provider", "expires_at", "config_id")

    def __init__(self, provider, expires_at, config_id):
        self.provider = provider
        self.expires_at = expires_at
        self.config_id = config_id


class PaymentRegistry:
    _cache: _CacheEntry | None = None
    _lock = Lock()

    @classmethod
    def get_active(cls) -> RazorpayProvider:
        active_id = settings_store.get("payment.active_provider_id")
        if active_id is None:
            raise AppError("Payments not configured. Add a payment provider in admin.",
                           status_code=503)
        return cls._get(int(active_id))

    @classmethod
    def get_by_id(cls, provider_id: int) -> RazorpayProvider:
        return cls._get(provider_id)

    @classmethod
    def invalidate(cls):
        with cls._lock:
            cls._cache = None

    @classmethod
    def _get(cls, provider_id: int) -> RazorpayProvider:
        ttl = settings_store.get_int("payment.cache_ttl_seconds", 30)
        now = time.monotonic()
        with cls._lock:
            if (cls._cache and cls._cache.expires_at > now
                    and cls._cache.config_id == provider_id):
                return cls._cache.provider

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
            cls._cache = _CacheEntry(provider, now + ttl, provider_id)
        return provider
