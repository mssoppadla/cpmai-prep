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

    # ── Listing control-plane (multi-gateway Phase 1) ────────────────
    # docs/payments-multi-gateway-spec.md §2. "Listed" = sellable for
    # NEW payments on a rail; is_enabled alone = still serviceable for
    # past payments (webhooks/refunds). Rows, not cached providers, so
    # admin listing changes are visible immediately.

    @classmethod
    def listed_rows(cls, currency: str) -> list:
        """Provider CONFIG ROWS sellable for this currency, in
        preference order. INR: the active_provider_id entry stays the
        canonical head (back-compat), then other INR-listed rows by
        priority. Non-INR: intl-listed rows by intl_rank, with the
        legacy non_inr_provider_id winning rank ties (back-compat)."""
        ccy = (currency or "INR").strip().upper()
        with SessionLocal() as db:
            q = (db.query(PaymentProviderConfig)
                 .filter(PaymentProviderConfig.is_enabled.is_(True)))
            if ccy == "INR":
                rows = (q.filter(PaymentProviderConfig.listed_for_inr.is_(True))
                        .order_by(PaymentProviderConfig.priority,
                                  PaymentProviderConfig.id).all())
                head_id = settings_store.get("payment.active_provider_id")
            else:
                rows = (q.filter(PaymentProviderConfig.listed_for_intl.is_(True))
                        .order_by(PaymentProviderConfig.intl_rank,
                                  PaymentProviderConfig.id).all())
                head_id = settings_store.get("payment.non_inr_provider_id")
            db.expunge_all()   # rows outlive the session (read-only use)
        if head_id is not None:
            head_id = int(head_id)
            rows.sort(key=lambda r: (r.id != head_id,))  # stable: head first
        return rows

    @classmethod
    def candidate_config_ids(cls, currency: str,
                             requested_id: "int | None" = None) -> list[int]:
        """Config ids to try for a NEW order, in order.

        requested_id (choice mode): must be in the listed set — an
        unlisted/disabled/unknown id raises 422-shaped AppError (a
        tampered client cannot summon a delisted gateway). Without a
        request: the full listed order (fallback iterates it when
        payments.fallback_enabled; otherwise callers use just the head).
        """
        listed = [r.id for r in cls.listed_rows(currency)]
        if requested_id is not None:
            if requested_id not in listed:
                raise AppError(
                    "Selected payment gateway is not available. Refresh "
                    "the page and pick from the shown options.",
                    status_code=422)
            return [requested_id]
        if not listed:
            ccy = (currency or "INR").strip().upper()
            if ccy == "INR":
                # Back-compat safety net: INR must never go dark because
                # listing flags are missing (pre-0047 rows) — fall back
                # to the classic active-provider setting.
                active_id = settings_store.get("payment.active_provider_id")
                if active_id is not None:
                    return [int(active_id)]
                raise AppError("Payments not configured. Add a payment "
                               "provider in admin.", status_code=503)
            raise AppError(
                f"No payment gateway is listed for {ccy}. List one in "
                "/admin/payment-providers (Listed for international), "
                "then retry.", status_code=503)
        return listed

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
