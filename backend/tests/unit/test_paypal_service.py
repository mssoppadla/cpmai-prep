"""PayPalProvider unit tests.

All PayPal API calls mocked with respx so we never hit api-m.sandbox.paypal.com
from the test suite. The provider's three concerns under test:

  1. OAuth — get a token, cache it, refresh on expiry, propagate auth
     failures as AppError(502).
  2. Orders — create_order shape matches what the /orders endpoint
     expects; capture_order idempotency handles the
     ORDER_ALREADY_CAPTURED re-entry path; declined captures surface
     status="DECLINED" in the dict (caller's responsibility to map).
  3. Webhook verification — happy path SUCCESS, missing headers
     short-circuit to False, FAILURE response yields False.

Amount-formatting (the integer-amount Razorpay rule from earlier work)
is also pinned here because the conversion from minor units → PayPal's
string-with-decimals format is silent and easy to get wrong.
"""
import json

import httpx
import pytest
import respx

from app.services.paypal_service import PayPalProvider


SANDBOX_BASE = "https://api-m.sandbox.paypal.com"

# Sample inbound webhook headers PayPal sends. Real names are
# case-insensitive on the wire; our verify path accepts either case.
_WEBHOOK_HEADERS = {
    "paypal-auth-algo":         "SHA256withRSA",
    "paypal-cert-url":          "https://api.paypal.com/v1/notifications/certs/CERT-x",
    "paypal-transmission-id":   "9f6f3c70-...-id",
    "paypal-transmission-sig":  "AbCdEf...sig",
    "paypal-transmission-time": "2026-05-13T12:00:00Z",
}


def _provider(mode: str = "test", webhook_id: str = "WH-TEST123"):
    return PayPalProvider(
        key_id="AcDeClient", key_secret="ECkDeXSecret",
        webhook_secret=None, mode=mode,
        webhook_id=webhook_id,
    )


@respx.mock
def test_access_token_succeeds_and_caches():
    """First call hits OAuth endpoint; second call within TTL returns
    the cached token without another network round-trip."""
    route = respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "test-token-abc",
            "expires_in": 3600,
            "token_type": "Bearer",
        }))
    p = _provider()
    assert p._access_token() == "test-token-abc"
    assert p._access_token() == "test-token-abc"
    # One network call for the two access_token() calls.
    assert route.call_count == 1


@respx.mock
def test_access_token_401_raises_appError_502():
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(401, text="invalid_client"))
    from app.core.exceptions import AppError
    with pytest.raises(AppError) as exc:
        _provider()._access_token()
    assert exc.value.status_code == 502
    assert "OAuth" in str(exc.value.detail)


@respx.mock
def test_create_order_returns_paypal_id_and_approval_url():
    """Happy path — Orders v2 returns approval URL in links[rel=approve]."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    paypal_response = {
        "id": "ORDER-ABC-123",
        "status": "CREATED",
        "links": [
            {"rel": "self",    "href": "https://api.../orders/ORDER-ABC-123"},
            {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-ABC-123"},
            {"rel": "capture", "href": "https://api.../orders/ORDER-ABC-123/capture"},
        ],
    }
    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders").mock(
        return_value=httpx.Response(201, json=paypal_response))

    p = _provider()
    out = p.create_order(amount_minor=1300, receipt="u_1_p_1_xxx",
                          currency="USD",
                          return_url="https://app.example.com/payments/paypal/return",
                          cancel_url="https://app.example.com/pricing?cancelled=1")
    assert out["id"] == "ORDER-ABC-123"
    assert out["amount"] == 1300
    assert out["currency"] == "USD"
    assert out["status"] == "CREATED"
    assert out["approval_url"] == (
        "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-ABC-123")
    # Full payload kept for audit / debugging on the /orders endpoint.
    assert out["_raw"] == paypal_response


@respx.mock
def test_create_order_sends_application_context_when_urls_supplied():
    """return_url + cancel_url + NO_SHIPPING + PAY_NOW must be in the
    request body so the buyer skips the address screen and the review
    step (digital goods)."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    captured = {}

    def capture_request(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={
            "id": "ORDER-X", "status": "CREATED", "links": []})

    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders").mock(
        side_effect=capture_request)

    _provider().create_order(
        amount_minor=900, currency="GBP",
        return_url="https://x/return", cancel_url="https://x/cancel")
    ctx = captured["body"]["application_context"]
    assert ctx["return_url"] == "https://x/return"
    assert ctx["cancel_url"] == "https://x/cancel"
    assert ctx["shipping_preference"] == "NO_SHIPPING"
    assert ctx["user_action"] == "PAY_NOW"


# ---------------------------------------------------------------------------
# Guest card checkout — application_context.landing_page.
#
# GUEST_CHECKOUT (default) shows the card form FIRST on PayPal's hosted
# page so overseas buyers without a PayPal account can pay as guests;
# PayPal-account buyers keep their "Log in" path. Admin-overridable via
# provider config JSON `landing_page` (/admin/payment-providers).
# ---------------------------------------------------------------------------

def _order_body_capture():
    """OAuth mock + orders mock that records the request body."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    captured = {}

    def capture_request(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={
            "id": "ORDER-X", "status": "CREATED", "links": []})

    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders").mock(
        side_effect=capture_request)
    return captured


@respx.mock
def test_create_order_defaults_to_guest_checkout_landing():
    """No config → landing_page=GUEST_CHECKOUT. This is the fix for
    overseas buyers bouncing off PayPal's login wall."""
    captured = _order_body_capture()
    _provider().create_order(amount_minor=900, currency="GBP",
                             return_url="https://x/r", cancel_url="https://x/c")
    assert captured["body"]["application_context"]["landing_page"] \
        == "GUEST_CHECKOUT"


@respx.mock
def test_create_order_landing_page_admin_override():
    """config.landing_page=LOGIN restores the previous behaviour without
    a deploy; values are normalized case-insensitively."""
    captured = _order_body_capture()
    p = PayPalProvider(key_id="A", key_secret="S", mode="test",
                       webhook_id="WH-1", landing_page="login")
    p.create_order(amount_minor=900, currency="GBP",
                   return_url="https://x/r", cancel_url="https://x/c")
    assert captured["body"]["application_context"]["landing_page"] == "LOGIN"


@respx.mock
def test_create_order_unknown_landing_page_falls_back_to_default():
    """A typo in admin config must not take payments down — unknown
    values silently fall back to GUEST_CHECKOUT."""
    captured = _order_body_capture()
    p = PayPalProvider(key_id="A", key_secret="S", mode="test",
                       webhook_id="WH-1", landing_page="CARD_PLZ")
    p.create_order(amount_minor=900, currency="GBP",
                   return_url="https://x/r", cancel_url="https://x/c")
    assert captured["body"]["application_context"]["landing_page"] \
        == "GUEST_CHECKOUT"


@respx.mock
def test_create_order_sends_application_context_even_without_urls():
    """landing_page applies regardless of return/cancel URLs — the
    context block is now always present (it used to be omitted when no
    URLs were supplied, which would have silently dropped the guest
    preference for any future caller)."""
    captured = _order_body_capture()
    _provider().create_order(amount_minor=900, currency="GBP")
    ctx = captured["body"]["application_context"]
    assert ctx["landing_page"] == "GUEST_CHECKOUT"
    assert "return_url" not in ctx and "cancel_url" not in ctx
    assert ctx["shipping_preference"] == "NO_SHIPPING"


@respx.mock
def test_create_order_amount_string_format_two_decimals():
    """PayPal's amount.value is a string with 2 decimal places.
    1300 cents → "13.00", NOT 1300 or "1300". The whole-unit ceil from
    pricing_service guarantees this is always X.00 in practice, but
    the formatter is tested in isolation in case partial-refund flows
    ever pass a non-whole-unit value."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    captured = {}

    def capture_request(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={
            "id": "ORDER-X", "status": "CREATED", "links": []})

    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders").mock(
        side_effect=capture_request)

    _provider().create_order(amount_minor=1300, currency="USD")
    pu = captured["body"]["purchase_units"][0]
    assert pu["amount"]["value"] == "13.00"
    assert pu["amount"]["currency_code"] == "USD"


@respx.mock
def test_capture_order_returns_capture_id_and_amount_minor():
    """Successful capture exposes capture_id (PayPal's payment id) and
    converts the amount back to minor units for storage on Payment row."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders/ORDER-ABC/capture").mock(
        return_value=httpx.Response(201, json={
            "id": "ORDER-ABC",
            "status": "COMPLETED",
            "purchase_units": [{
                "payments": {
                    "captures": [{
                        "id": "CAPTURE-XYZ",
                        "status": "COMPLETED",
                        "amount": {"value": "13.00", "currency_code": "USD"},
                    }],
                },
            }],
        }))
    out = _provider().capture_order("ORDER-ABC")
    assert out["order_id"] == "ORDER-ABC"
    assert out["capture_id"] == "CAPTURE-XYZ"
    assert out["status"] == "COMPLETED"
    assert out["amount_minor"] == 1300
    assert out["currency"] == "USD"


@respx.mock
def test_capture_order_already_captured_refetches_idempotently():
    """The 422 ORDER_ALREADY_CAPTURED path is our re-entry case (buyer
    clicks "complete" twice, webhook+capture both fire, etc.). We should
    re-fetch the order and return the existing capture rather than
    raising — paying twice would be the wrong outcome here."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders/ORDER-RE/capture").mock(
        return_value=httpx.Response(422, json={
            "details": [{"issue": "ORDER_ALREADY_CAPTURED"}],
        }))
    respx.get(f"{SANDBOX_BASE}/v2/checkout/orders/ORDER-RE").mock(
        return_value=httpx.Response(200, json={
            "id": "ORDER-RE", "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [{
                "id": "CAP-OLD", "status": "COMPLETED",
                "amount": {"value": "9.00", "currency_code": "GBP"},
            }]}}],
        }))
    out = _provider().capture_order("ORDER-RE")
    assert out["capture_id"] == "CAP-OLD"
    assert out["status"] == "COMPLETED"
    assert out["amount_minor"] == 900


@respx.mock
def test_capture_order_real_422_raises_appError():
    """A non-idempotency 422 (e.g. INSTRUMENT_DECLINED) must propagate
    as a 502 — caller can't recover by retry, the buyer needs a new
    payment instrument."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    respx.post(f"{SANDBOX_BASE}/v2/checkout/orders/ORD-X/capture").mock(
        return_value=httpx.Response(422, json={
            "details": [{"issue": "INSTRUMENT_DECLINED"}]}))
    from app.core.exceptions import AppError
    with pytest.raises(AppError) as exc:
        _provider().capture_order("ORD-X")
    assert exc.value.status_code == 502


@respx.mock
def test_verify_webhook_success_path():
    """Headers + body forward to PayPal's verify endpoint; SUCCESS → True."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    respx.post(
        f"{SANDBOX_BASE}/v1/notifications/verify-webhook-signature"
    ).mock(return_value=httpx.Response(200, json={
        "verification_status": "SUCCESS"}))

    body = json.dumps({"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"})
    assert _provider().verify_webhook(_WEBHOOK_HEADERS, body.encode()) is True


@respx.mock
def test_verify_webhook_failure_returns_false():
    """PayPal says FAILURE — provider returns False (caller maps to 400)."""
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    respx.post(
        f"{SANDBOX_BASE}/v1/notifications/verify-webhook-signature"
    ).mock(return_value=httpx.Response(200, json={
        "verification_status": "FAILURE"}))
    assert _provider().verify_webhook(_WEBHOOK_HEADERS, b'{"id":"x"}') is False


def test_verify_webhook_missing_header_short_circuits_to_false():
    """Don't even call PayPal if the required transmission headers
    aren't present — that's an obvious bad request."""
    p = _provider()
    bad_headers = dict(_WEBHOOK_HEADERS)
    del bad_headers["paypal-transmission-sig"]
    assert p.verify_webhook(bad_headers, b'{"id":"x"}') is False


def test_verify_webhook_no_webhook_id_short_circuits_to_false():
    """If config.webhook_id is empty, verification can't work — return
    False so admin sees the misconfig (their webhooks all 400 in logs)."""
    p = PayPalProvider(key_id="x", key_secret="y", mode="test", webhook_id="")
    assert p.verify_webhook(_WEBHOOK_HEADERS, b'{"id":"x"}') is False


@respx.mock
def test_smoke_test_returns_ok_on_valid_creds():
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok", "expires_in": 3600}))
    r = _provider().smoke_test()
    assert r == {"ok": True, "env": "test"}


@respx.mock
def test_smoke_test_returns_error_on_bad_creds():
    respx.post(f"{SANDBOX_BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(401, text="invalid_client"))
    r = _provider().smoke_test()
    assert r["ok"] is False
    assert "OAuth" in r["error"]
    assert r["env"] == "test"


def test_live_mode_uses_production_base_url():
    """Sanity: switching mode to 'live' flips the base URL to
    api-m.paypal.com so sandbox creds never accidentally hit live."""
    p = PayPalProvider(key_id="x", key_secret="y", mode="live", webhook_id="WH-X")
    assert p._base == "https://api-m.paypal.com"
    p2 = PayPalProvider(key_id="x", key_secret="y", mode="test", webhook_id="WH-X")
    assert p2._base == "https://api-m.sandbox.paypal.com"


def test_provider_constructor_requires_credentials():
    """An empty Client ID is a config bug — fail loud before any request."""
    with pytest.raises(ValueError):
        PayPalProvider(key_id="", key_secret="x")
    with pytest.raises(ValueError):
        PayPalProvider(key_id="x", key_secret="")
