"""PayPal Orders v2 provider.

Mirrors RazorpayProvider's interface as closely as possible so the
rest of the codebase (PaymentRegistry, /payments endpoints) can hold
a single mental model: one `Provider` per gateway, with create_order
+ verify_webhook_signature + smoke_test methods.

Two places PayPal diverges from Razorpay's flow — each handled here:

  1. **Two-step payment** — Razorpay's payment.captured webhook IS the
     authorization+capture in one shot. PayPal Orders v2 separates them:
     the buyer approves on PayPal's domain, then OUR backend must call
     `capture_order(order_id)` to actually move the money. The frontend
     PayPal Smart Button does this via the `onApprove` callback hitting
     our /payments/paypal/capture endpoint.

  2. **Webhook authentication** — Razorpay signs the body with a shared
     HMAC-SHA256 secret. PayPal uses certificate-based signing: each
     event arrives with a transmission-id, cert-url, signature, etc.,
     and we ask PayPal's `/v1/notifications/verify-webhook-signature`
     to do the crypto verification on their end. We never see a
     "webhook secret" — only a webhook_id (the ID of the webhook config
     we registered in PayPal's dashboard, used as one input to their
     verification API).

Amount format note:
  Razorpay's `amount` field is an integer in subunits (paise/cents).
  PayPal's `amount.value` is a STRING in MAJOR units with two decimal
  places (e.g. "13.00", not 1300 or "1300"). We convert from our
  internal minor-unit ints at the boundary. The whole-unit rounding
  applied in pricing_service._build_display_block guarantees the
  PayPal-bound amount is always a clean major-unit value.
"""
import json
import time
from base64 import b64encode
from typing import Optional

import httpx

from app.core.exceptions import AppError


# Two-decimal-place currencies cover everything in our default picker
# (USD/EUR/GBP/AUD/CAD/SGD/AED/...). If JPY/KRW (zero-decimal) ever
# enter the picker, this needs a per-currency exception map — see the
# whole-unit-rounding caveat in pricing_service.py.
_DECIMALS_PER_MAJOR = 2

# Landing-page preference — what the buyer sees FIRST on PayPal's
# hosted page:
#   GUEST_CHECKOUT — card form first ("guest" pay-by-card), with
#                    "Log in to PayPal" as the secondary option.
#   LOGIN          — PayPal login wall first (the old implicit default).
#   NO_PREFERENCE  — PayPal decides per buyer context. OUR DEFAULT.
# Admin-overridable via the provider's config JSON (`landing_page`) on
# /admin/payment-providers — no deploy needed to flip behaviour.
#
# Why NO_PREFERENCE default (prod incident 2026-07-12): forcing the
# card-form-first page (GUEST_CHECKOUT→BILLING) breaks buyers for whom
# PayPal does NOT allow guest card processing on this merchant account
# — a UK buyer got PayPal's generic "We're sorry, something went
# wrong" on the guest form, while the SAME buyer paying after logging
# in to PayPal succeeded (guest eligibility is per merchant-account
# capability + buyer-country rules, e.g. PSD2/3-D Secure in the UK/EU;
# nothing our API request can grant). NO_PREFERENCE lets PayPal show
# the card form only where guest checkout is actually eligible and the
# login page elsewhere — the login flow is unaffected either way.
# Operators who have confirmed guest-card capability with PayPal can
# still force card-first via config landing_page=GUEST_CHECKOUT.
#
# WIRE FORMAT TRAP (prod incident 2026-07-09): the LEGACY
# ``application_context.landing_page`` we send only accepts
# LOGIN | BILLING | NO_PREFERENCE — sending "GUEST_CHECKOUT" there gets
# HTTP 400 INVALID_PARAMETER_VALUE and every non-INR payment fails.
# "GUEST_CHECKOUT" is the NEWER ``payment_source.paypal
# .experience_context`` spelling of the same card-form-first behaviour.
# We keep GUEST_CHECKOUT as the admin-facing/config value (it says what
# it does) and translate to BILLING at the wire boundary. If this
# provider ever migrates to experience_context, drop the mapping.
_LANDING_PAGES = ("GUEST_CHECKOUT", "LOGIN", "NO_PREFERENCE")
_DEFAULT_LANDING_PAGE = "NO_PREFERENCE"
_LANDING_PAGE_WIRE = {
    "GUEST_CHECKOUT": "BILLING",
    "LOGIN": "LOGIN",
    "NO_PREFERENCE": "NO_PREFERENCE",
}


class PayPalProvider:
    """REST client for PayPal Orders v2.

    Args:
        key_id: PayPal Client ID (the public-side identifier; safe to
            ship in frontend Smart Button SDK URL).
        key_secret: PayPal Client Secret (kept server-side, used only
            for the OAuth token exchange).
        webhook_secret: Unused for PayPal — keeps the constructor
            signature compatible with RazorpayProvider so PaymentRegistry
            doesn't need to branch. Will always be None for PayPal.
        mode: "test" (sandbox) or "live". Drives the base URL.
        **config: Extra fields from PaymentProviderConfig.config JSON.
            Must contain `webhook_id` — the ID of the webhook registered
            in PayPal's developer dashboard, used as input to PayPal's
            verify-webhook-signature API.

    Caches the OAuth access token in-instance with TTL. PaymentRegistry
    already TTL-caches the provider INSTANCE, so refreshing rotates
    naturally on the same cadence as credential changes.
    """

    name = "paypal"

    _SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
    _LIVE_BASE    = "https://api-m.paypal.com"

    def __init__(self, key_id: str, key_secret: str,
                 webhook_secret: Optional[str] = None,
                 mode: str = "test", **config):
        if not key_id or not key_secret:
            raise ValueError("PayPal provider requires key_id + key_secret.")
        self.key_id = key_id
        self._key_secret = key_secret
        # PayPal doesn't use a shared webhook secret — webhook_id lives
        # in config JSON instead. We KEEP this parameter so PaymentRegistry
        # constructs the same way for every provider, but ignore it.
        self._webhook_secret = webhook_secret  # always None for PayPal
        self.mode = mode if mode in ("test", "live") else "test"
        self.config = config
        self._webhook_id = (config or {}).get("webhook_id") or ""
        # Buyer-facing landing page on PayPal's hosted checkout. Unknown
        # config values fall back to the default rather than erroring —
        # a typo in admin config must not take payments down. "BILLING"
        # (the legacy wire spelling) is accepted as a synonym of
        # GUEST_CHECKOUT in case an operator sets the raw API value.
        raw_lp = str((config or {}).get("landing_page") or
                     _DEFAULT_LANDING_PAGE).strip().upper()
        if raw_lp == "BILLING":
            raw_lp = "GUEST_CHECKOUT"
        self._landing_page = (raw_lp if raw_lp in _LANDING_PAGES
                              else _DEFAULT_LANDING_PAGE)

        self._base = self._LIVE_BASE if self.mode == "live" else self._SANDBOX_BASE
        # 8-second connect, 20-second read — PayPal's API is occasionally
        # slow during US business hours. Keep both well under the FastAPI
        # default 60s request timeout so we surface a clean 502 if PayPal
        # itself is having a bad day.
        self._http = httpx.Client(base_url=self._base, timeout=httpx.Timeout(
            connect=8.0, read=20.0, write=10.0, pool=5.0))

        # Token cache. PayPal access tokens are typically valid 9 hours;
        # we expire 60 seconds early to defend against clock skew.
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ---------- OAuth ----------

    def _access_token(self) -> str:
        """Return a valid bearer token, refreshing if near expiry."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        creds = f"{self.key_id}:{self._key_secret}".encode()
        basic = b64encode(creds).decode()
        try:
            r = self._http.post(
                "/v1/oauth2/token",
                headers={"Authorization": f"Basic {basic}",
                          "Accept": "application/json"},
                data={"grant_type": "client_credentials"},
            )
        except httpx.HTTPError as e:
            raise AppError(
                f"PayPal OAuth network error: {type(e).__name__}: {e}",
                status_code=502)
        if r.status_code != 200:
            # 401 = bad creds (most common operational failure).
            raise AppError(
                f"PayPal OAuth failed (HTTP {r.status_code}): {r.text[:300]}",
                status_code=502)
        body = r.json()
        self._token = body["access_token"]
        # Refresh 60s before actual expiry. expires_in is in seconds.
        self._token_expires_at = time.monotonic() + max(0, body.get("expires_in", 0) - 60)
        return self._token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
                "Accept": "application/json"}

    # ---------- Public API (matches RazorpayProvider where possible) ----------

    def create_order(self, amount_minor: int,
                     receipt: Optional[str] = None,
                     currency: str = "USD",
                     return_url: Optional[str] = None,
                     cancel_url: Optional[str] = None) -> dict:
        """Create a PayPal Orders v2 order.

        Args:
            amount_minor: Total to charge in MINOR units (e.g. cents).
                Must already be ceiled to a whole major unit (see
                pricing_service._build_display_block — for non-INR
                we enforce % 100 == 0 to satisfy PayPal/Razorpay
                International integer-amount rules).
            receipt: Our internal idempotency key. Passed to PayPal as
                `custom_id` so it appears in the merchant's PayPal
                transaction log when reconciling.
            currency: ISO-4217 code. PayPal supports ~25 currencies
                for receiving; if the merchant's account doesn't support
                the requested currency, PayPal returns a 422 with code
                CURRENCY_NOT_SUPPORTED — we propagate that verbatim.

        Returns:
            A dict with the same outer shape as Razorpay's order.create:
                {
                    "id":     "<paypal_order_id>",
                    "amount": amount_minor,
                    "currency": currency,
                    "status": "CREATED" | "PAYER_ACTION_REQUIRED" | ...,
                    "approval_url": "https://www.paypal.com/checkoutnow?token=..."
                }
            The `approval_url` is unique to PayPal — frontend either
            redirects there OR feeds the order id into the Smart Button
            SDK (preferred — no full-page redirect for the buyer).

        Raises:
            AppError(502) on network or API errors.
        """
        value_str = self._format_amount(amount_minor, currency)
        body: dict = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {
                    "currency_code": currency.upper(),
                    "value": value_str,
                },
                # custom_id surfaces in the merchant's PayPal report so
                # reconciliation against our Payment row is one lookup.
                "custom_id": receipt or "",
                "invoice_id": receipt or None,
            }],
        }
        # application_context controls the buyer-facing flow on PayPal's
        # domain. We always pass return/cancel so the buyer lands back on
        # a known frontend route, where we capture (return) or surface a
        # cancel message (cancel).
        #
        # landing_page=GUEST_CHECKOUT (default; admin-overridable via
        # provider config) shows the CARD FORM first so overseas buyers
        # without a PayPal account can pay as guests — PayPal-account
        # holders still get a "Log in" link, so the existing flow keeps
        # working. NOTE: guest card eligibility is ultimately PayPal's
        # per-country/risk decision, and the merchant account needs
        # "PayPal account optional" = On.
        body["application_context"] = {
            **({"return_url": return_url} if return_url else {}),
            **({"cancel_url": cancel_url} if cancel_url else {}),
            # Translated to the LEGACY wire vocabulary — GUEST_CHECKOUT
            # must go out as BILLING here (see _LANDING_PAGE_WIRE).
            "landing_page": _LANDING_PAGE_WIRE[self._landing_page],
            # NO_SHIPPING: digital goods, no address needed.
            # PAY_NOW: skip PayPal's "review your order" intermediate.
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
        }
        try:
            r = self._http.post(
                "/v2/checkout/orders",
                headers=self._auth_headers(),
                content=json.dumps(body),
            )
        except httpx.HTTPError as e:
            raise AppError(
                f"PayPal order.create network error: {type(e).__name__}: {e}",
                status_code=502)
        if r.status_code not in (200, 201):
            # paypal-debug-id is THE handle PayPal support asks for —
            # surface it in the error so ops can quote it verbatim.
            raise AppError(
                f"PayPal rejected order (HTTP {r.status_code}, "
                f"debug-id {r.headers.get('paypal-debug-id', 'n/a')}): "
                f"{r.text[:300]}",
                status_code=502)
        payload = r.json()
        # Pull out the "approve" rel link — what the buyer is redirected
        # to OR what the Smart Button consumes.
        approval_url = None
        for link in payload.get("links", []):
            if link.get("rel") == "approve":
                approval_url = link.get("href")
                break
        return {
            "id": payload["id"],
            "amount": amount_minor,
            "currency": currency.upper(),
            "status": payload.get("status"),
            "approval_url": approval_url,
            # Keep the full PayPal payload for audit; matches Razorpay's
            # habit of returning the raw provider response.
            "_raw": payload,
        }

    def capture_order(self, order_id: str) -> dict:
        """Capture an approved PayPal order. PayPal-specific (Razorpay's
        flow auto-captures via payment.captured webhook).

        Called by /payments/paypal/capture after the frontend Smart
        Button's onApprove callback fires. Idempotent — capturing an
        already-captured order returns the existing capture record
        (PayPal returns 422 ORDER_ALREADY_CAPTURED which we treat as
        success and re-fetch the capture).

        Returns:
            {
                "order_id":   "<paypal order id>",
                "capture_id": "<paypal capture id>",     # the actual payment id
                "status":     "COMPLETED" | "PENDING" | "DECLINED" | ...,
                "amount_minor": <int>,
                "currency":    "<3-letter code>",
                "_raw":        <full payload>,
            }

        Raises:
            AppError(502) on network/API failure.
            AppError(400) on declined captures (DECLINED status).
        """
        try:
            r = self._http.post(
                f"/v2/checkout/orders/{order_id}/capture",
                headers=self._auth_headers(),
                content="{}",   # PayPal requires an empty JSON body
            )
        except httpx.HTTPError as e:
            raise AppError(
                f"PayPal capture network error: {type(e).__name__}: {e}",
                status_code=502)
        # 201 = first-time capture. 422 with ORDER_ALREADY_CAPTURED is
        # our re-entry path — we want it to look like success because
        # the user has already paid; webhook will sort the rest.
        if r.status_code == 422:
            err = r.json() if r.text else {}
            details = err.get("details", [{}])[0]
            if details.get("issue") == "ORDER_ALREADY_CAPTURED":
                # Re-fetch order to get the existing capture details.
                return self._refetch_capture(order_id)
        if r.status_code not in (200, 201):
            raise AppError(
                f"PayPal capture failed (HTTP {r.status_code}, "
                f"debug-id {r.headers.get('paypal-debug-id', 'n/a')}): "
                f"{r.text[:300]}",
                status_code=502)
        payload = r.json()
        return self._extract_capture(payload, fallback_order_id=order_id)

    def _refetch_capture(self, order_id: str) -> dict:
        """Re-read an already-captured order. Idempotency path."""
        try:
            r = self._http.get(
                f"/v2/checkout/orders/{order_id}",
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as e:
            raise AppError(
                f"PayPal order refetch network error: {type(e).__name__}: {e}",
                status_code=502)
        if r.status_code != 200:
            raise AppError(
                f"PayPal order refetch failed (HTTP {r.status_code}): "
                f"{r.text[:300]}",
                status_code=502)
        return self._extract_capture(r.json(), fallback_order_id=order_id)

    @staticmethod
    def _extract_capture(payload: dict, *, fallback_order_id: str) -> dict:
        """Pull the first capture out of an Orders-v2 payload."""
        pu = (payload.get("purchase_units") or [{}])[0]
        caps = (pu.get("payments", {}).get("captures") or [{}])
        cap = caps[0] if caps else {}
        amt = cap.get("amount", {}) or {}
        try:
            amount_minor = int(round(float(amt.get("value", "0")) * 100))
        except (TypeError, ValueError):
            amount_minor = 0
        return {
            "order_id":   payload.get("id") or fallback_order_id,
            "capture_id": cap.get("id"),
            "status":     cap.get("status") or payload.get("status"),
            "amount_minor": amount_minor,
            "currency":   amt.get("currency_code"),
            "_raw":       payload,
        }

    # ---------- Webhook verification ----------

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Razorpay-compatible signature (single string) — NOT used for
        PayPal. PayPal needs the whole headers dict + raw body. Kept on
        the interface so PaymentRegistry callers can stay generic;
        always returns False. Use ``verify_webhook(headers, body)``
        instead for PayPal-shaped verification.
        """
        return False

    def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """Authenticate an inbound PayPal webhook.

        Calls PayPal's verify-webhook-signature API with our stored
        webhook_id + the inbound transmission headers + body. PayPal
        does the certificate chain validation and HMAC math; we just
        check the response is verification_status=SUCCESS.

        Returns False on any failure (network error, missing header,
        bad signature). Caller maps False → HTTP 400.
        """
        if not self._webhook_id:
            return False
        # PayPal headers are case-insensitive on the wire; FastAPI lowercases
        # them by default. Accept either case for safety.
        def h(k: str) -> str:
            return (headers.get(k) or headers.get(k.lower())
                    or headers.get(k.upper()) or "")
        required = ["paypal-auth-algo", "paypal-cert-url",
                    "paypal-transmission-id", "paypal-transmission-sig",
                    "paypal-transmission-time"]
        if any(not h(k) for k in required):
            return False
        try:
            event = json.loads(body)
        except (ValueError, TypeError):
            return False
        verify_body = {
            "auth_algo":         h("paypal-auth-algo"),
            "cert_url":          h("paypal-cert-url"),
            "transmission_id":   h("paypal-transmission-id"),
            "transmission_sig":  h("paypal-transmission-sig"),
            "transmission_time": h("paypal-transmission-time"),
            "webhook_id":        self._webhook_id,
            "webhook_event":     event,
        }
        try:
            r = self._http.post(
                "/v1/notifications/verify-webhook-signature",
                headers=self._auth_headers(),
                content=json.dumps(verify_body),
            )
        except httpx.HTTPError:
            return False
        if r.status_code != 200:
            return False
        return r.json().get("verification_status") == "SUCCESS"

    # ---------- Diagnostics ----------

    def smoke_test(self) -> dict:
        """Lightweight connectivity check — exchanges OAuth creds.

        Doesn't create any test orders (would pollute the merchant's
        PayPal report). Just confirms Client ID + Secret authenticate
        against the configured environment.
        """
        try:
            self._access_token()
            return {"ok": True, "env": self.mode}
        except AppError as e:
            return {"ok": False, "error": str(e.detail), "env": self.mode}
        except Exception as e:
            return {"ok": False, "error": str(e), "env": self.mode}

    # ---------- Internal helpers ----------

    @staticmethod
    def _format_amount(amount_minor: int, currency: str) -> str:
        """Convert minor units → PayPal's string-with-decimals format.

        amount_minor=1300, currency="USD" → "13.00"
        amount_minor=900,  currency="GBP" → "9.00"

        Currencies with non-2-decimal ratios (JPY/KRW/HUF — not in our
        default picker) need a per-currency override; for now we hard-
        cap at 2 to match what _build_display_block produces.
        """
        # The whole-unit ceil in pricing_service guarantees amount_minor
        # is a multiple of 100 for non-INR, so this is always X.00 —
        # but we don't enforce that here in case a future caller passes
        # a pre-ceil amount (e.g. for partial refunds someday).
        major = amount_minor / (10 ** _DECIMALS_PER_MAJOR)
        return f"{major:.{_DECIMALS_PER_MAJOR}f}"
