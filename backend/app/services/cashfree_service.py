"""Cashfree PG (v3 API) client — hosted-checkout (A1) flow.

Mirrors RazorpayProvider/PayPalProvider so PaymentRegistry needs no
branching:

  * create_order(...)            → creates a PG order; returns our
                                   order id + payment_session_id (the
                                   frontend hands the session to
                                   Cashfree's JS which redirects to the
                                   HOSTED payment page).
  * fetch_order(order_id)        → order status ('PAID' = captured);
                                   used by /payments/cashfree/verify on
                                   the buyer's return.
  * fetch_order_payments(...)    → reconcile-sweep compatible: list of
                                   attempts shaped like Razorpay's
                                   ({id, status: 'captured'|...}).
  * verify_webhook(ts, body, sig)→ Cashfree signs webhooks with
                                   base64(HMAC-SHA256(timestamp + raw
                                   body, webhook secret)).

mode "test" → sandbox.cashfree.com, "live" → api.cashfree.com.
key_id = Cashfree App ID (x-client-id), key_secret = secret key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.request
import urllib.error

API_VERSION = "2023-08-01"


class CashfreeProvider:
    name = "cashfree"

    def __init__(self, key_id: str, key_secret: str,
                 webhook_secret: str | None = None,
                 mode: str = "test", **config):
        self.key_id = key_id
        self._key_secret = key_secret
        # Cashfree signs webhooks with the SAME secret key by default;
        # a separately-configured webhook secret (their dashboard allows
        # one) takes precedence when provided.
        self._webhook_secret = webhook_secret or key_secret
        self.mode = mode
        self.base = ("https://api.cashfree.com/pg" if mode == "live"
                     else "https://sandbox.cashfree.com/pg")
        self.config = config

    # ── HTTP plumbing (stdlib on purpose — no new dependency) ────────
    def _request(self, method: str, path: str,
                 payload: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=(json.dumps(payload).encode() if payload is not None
                  else None),
            method=method,
            headers={
                "x-client-id": self.key_id,
                "x-client-secret": self._key_secret,
                "x-api-version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            raise RuntimeError(
                f"Cashfree API {e.code} on {method} {path}: {body}"
            ) from e

    # ── order lifecycle ──────────────────────────────────────────────
    def create_order(self, amount_minor: int, receipt: str | None = None,
                     currency: str = "INR",
                     customer: dict | None = None,
                     return_url: str | None = None, **_kw) -> dict:
        """Create a PG order. Cashfree amounts are MAJOR units with
        decimals; we hold minor units everywhere, so convert here.
        `customer` needs customer_id/email/phone — Cashfree requires a
        phone; callers pass a placeholder when the user has none."""
        cust = customer or {}
        payload = {
            "order_id": receipt or None,
            "order_amount": round(amount_minor / 100.0, 2),
            "order_currency": currency,
            "customer_details": {
                "customer_id": str(cust.get("id") or "guest"),
                "customer_email": cust.get("email") or "",
                "customer_phone": cust.get("phone") or "9999999999",
            },
        }
        if return_url:
            payload["order_meta"] = {"return_url": return_url}
        data = self._request("POST", "/orders", payload)
        return {
            "id": data.get("order_id"),
            "payment_session_id": data.get("payment_session_id"),
            "amount": amount_minor,
            "currency": currency,
        }

    def fetch_order(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}")

    def fetch_order_payments(self, order_id: str) -> list[dict]:
        """Reconcile-sweep seam — same shape as Razorpay's: a list of
        attempts with `id` + `status`, where 'captured' means money
        moved (Cashfree calls it SUCCESS)."""
        rows = self._request("GET", f"/orders/{order_id}/payments")
        out = []
        for r in _iter(rows):
            out.append({
                "id": str(r.get("cf_payment_id") or ""),
                "status": ("captured"
                           if (r.get("payment_status") or "") == "SUCCESS"
                           else str(r.get("payment_status") or "").lower()),
            })
        return out

    # ── webhook verification ─────────────────────────────────────────
    def verify_webhook(self, timestamp: str, body: bytes,
                       signature: str) -> bool:
        """x-webhook-signature = base64(HMAC-SHA256(timestamp + rawBody,
        secret)). Constant-time compare; empty inputs never verify."""
        if not (timestamp and body and signature and self._webhook_secret):
            return False
        expected = base64.b64encode(hmac.new(
            self._webhook_secret.encode(),
            timestamp.encode() + body,
            hashlib.sha256,
        ).digest()).decode()
        return hmac.compare_digest(expected, signature)

    def smoke_test(self) -> dict:
        """Auth check: fetch a definitely-absent order. 404 = creds OK;
        401/403 = bad keys."""
        try:
            self._request("GET", "/orders/cf_smoke_test_absent_order")
            return {"ok": True}
        except RuntimeError as e:
            msg = str(e)
            if " 404 " in msg or "order_not_found" in msg:
                return {"ok": True}
            return {"ok": False, "error": msg[:200]}


def _iter(rows):
    """Cashfree list endpoints return a bare JSON array; tolerate both
    a list and an {items: []} wrapper defensively."""
    if isinstance(rows, list):
        return rows
    if isinstance(rows, dict):
        return rows.get("items") or []
    return []
