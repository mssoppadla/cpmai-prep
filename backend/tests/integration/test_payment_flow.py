"""End-to-end payment flow: orders → verify → subscription created.

Mocks the Razorpay provider so tests don't make real HTTP calls. Asserts
on the persisted Payment / Subscription / OfferRedemption rows so any
regression in the wiring fails loudly.
"""
import pytest
from datetime import datetime, timezone
from app.models.plan import Plan, PlanExamSet
from app.models.subscription import Subscription
from app.models.offer import OfferCode, OfferRedemption
from app.models.payment import Payment, WebhookEvent
from app.services.payment_registry import PaymentRegistry
from tests.conftest import auth_header


# ----------------------------------------------------------- fake provider
class FakeProvider:
    """Same surface as RazorpayProvider but no network.

    ``name = "razorpay"`` because /verify and the Razorpay webhook now
    gate on provider_name to dispatch between the Razorpay HMAC path
    and the PayPal certificate-verify path — the fake represents a
    Razorpay-rail provider in tests.
    """
    name = "razorpay"; key_id = "rzp_test_fake"; mode = "test"

    def __init__(self):
        self._sigs: dict[str, str] = {}    # order_id|payment_id → signature
        self.last_order_amount = None

    def create_order(self, amount_paise, receipt=None, currency="INR"):
        self.last_order_amount = amount_paise
        oid = f"order_{receipt or 'test'}"
        return {"id": oid, "amount": amount_paise, "currency": currency,
                 "receipt": receipt}

    def verify_payment_signature(self, order_id, payment_id, signature):
        return signature == f"sig:{order_id}:{payment_id}"

    def verify_webhook_signature(self, payload, signature):
        return signature == "fake-webhook-sig"


@pytest.fixture
def fake_provider(monkeypatch):
    """Wire FakeProvider into every PaymentRegistry entry point so the
    /orders, /verify, and webhook code paths all use it regardless of
    currency. Existing tests rely on a single shared instance to make
    assertions on ``last_order_amount`` after the request."""
    p = FakeProvider()
    monkeypatch.setattr(PaymentRegistry, "get_active",
                        classmethod(lambda cls: p))
    # /orders now routes through get_for_currency. INR currency lands
    # on the active provider (the fake); non-INR also routes here in
    # tests that don't override (the fx_live_settings tests use this
    # fixture for the non-INR rail too — fake-as-paypal stand-in).
    monkeypatch.setattr(PaymentRegistry, "get_for_currency",
                        classmethod(lambda cls, ccy: p))
    return p


def _seed_plan(db, **kw) -> Plan:
    defaults = dict(name="Exam Bundle", slug="exam-bundle",
                    bundle_type="exam_bundle", base_price_paise=99900,
                    currency="INR", duration_days=365, perks={},
                    is_active=True, display_order=10)
    defaults.update(kw)
    p = Plan(**defaults)
    db.add(p); db.commit(); db.refresh(p)
    return p


# ====================================================== happy-path order
def test_order_uses_server_computed_price(client, db, user, fake_provider):
    _seed_plan(db, base_price_paise=100_000, discount_price_paise=80_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle"})
    assert r.status_code == 201, r.text
    body = r.json()
    # Even though the client sent NO amount, server applied the discount.
    assert body["amount"] == 80_000
    assert fake_provider.last_order_amount == 80_000
    assert body["base_amount"] == 100_000
    assert body["discount_amount"] == 20_000


def test_order_records_referrer(client, db, user, fake_provider):
    _seed_plan(db, base_price_paise=10_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "referrer": "alice@example.com"})
    assert r.status_code == 201
    pay = (db.query(Payment).filter_by(provider_order_id=r.json()["order_id"])
           .first())
    assert pay.referrer == "alice@example.com"


def test_order_unknown_plan_404(client, user, fake_provider):
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "ghost"})
    assert r.status_code == 404


def test_order_requires_auth(client, fake_provider):
    r = client.post("/api/v1/payments/orders", json={
        "plan_slug": "any"})
    assert r.status_code == 401


# ============================================================ offer flow
def test_order_with_valid_offer_charges_discounted_amount(
        client, db, user, fake_provider):
    _seed_plan(db, base_price_paise=100_000)
    db.add(OfferCode(code="SAVE20", discount_type="percent",
                     discount_value=20, is_active=True))
    db.commit()

    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "offer_code": "save20"})
    assert r.status_code == 201
    body = r.json()
    assert body["offer_applied"] is True
    assert body["amount"] == 80_000


def test_order_reserves_redemption_seat(client, db, user, fake_provider):
    _seed_plan(db, base_price_paise=10_000)
    db.add(OfferCode(code="ONCE", discount_type="percent",
                     discount_value=10,
                     max_redemptions=1, used_count=0, is_active=True))
    db.commit()

    h = auth_header(client, user.email)
    r1 = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "offer_code": "once"})
    assert r1.status_code == 201
    code = db.query(OfferCode).filter_by(code="ONCE").first()
    assert code.used_count == 1

    # Second order with the same code — quote sees max-reached and
    # gracefully falls back; price stays at base, no further reserve.
    r2 = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "offer_code": "once"})
    assert r2.status_code == 201
    assert r2.json()["offer_applied"] is False
    db.refresh(code); assert code.used_count == 1


# ======================================================= verify → sub
def test_verify_creates_subscription_with_expiry(
        client, db, user, fake_provider):
    plan = _seed_plan(db, base_price_paise=10_000, duration_days=365)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle"})
    oid = r.json()["order_id"]
    pid = "pay_test_xyz"
    r2 = client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid, "payment_id": pid,
        "signature": f"sig:{oid}:{pid}",
    })
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "active"
    assert body["plan_slug"] == "exam-bundle"
    sub = (db.query(Subscription)
           .filter_by(user_id=user.id, plan_id=plan.id).first())
    assert sub is not None
    assert sub.status == "active"
    assert sub.expires_at is not None
    # ~365 days in the future (within a generous 1-day window).
    delta = sub.expires_at - datetime.now(timezone.utc)
    assert 364 <= delta.days <= 366


def test_verify_bad_signature_400(client, db, user, fake_provider):
    _seed_plan(db, base_price_paise=10_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle"})
    oid = r.json()["order_id"]
    r2 = client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid, "payment_id": "p", "signature": "WRONG",
    })
    assert r2.status_code == 400


def test_verify_persists_offer_redemption(client, db, user, fake_provider):
    plan = _seed_plan(db, base_price_paise=10_000)
    db.add(OfferCode(code="USE", discount_type="percent",
                     discount_value=10, is_active=True))
    db.commit()
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "offer_code": "use"})
    oid = r.json()["order_id"]
    client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid, "payment_id": "p1",
        "signature": f"sig:{oid}:p1",
    })
    red = db.query(OfferRedemption).first()
    assert red is not None
    assert red.user_id == user.id
    assert red.plan_id == plan.id
    assert red.discount_paise == 1_000


def test_order_charges_gst_inclusive_amount(client, db, user, fake_provider, monkeypatch):
    """GST is the price the user actually pays. The amount sent to
    Razorpay's order.create call must be subtotal + GST, not subtotal."""
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: (
            18 if k == "pricing.gst_percent"
            else False if k == "pricing.stack_offer_with_discount"
            else default))
    _seed_plan(db, base_price_paise=100_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle"})
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == 118_000              # 100k + 18% GST
    assert body["subtotal_amount"] == 100_000
    assert body["gst_percent"] == 18
    assert body["gst_amount"] == 18_000
    assert fake_provider.last_order_amount == 118_000


def test_verify_renew_extends_expiry(client, db, user, fake_provider):
    plan = _seed_plan(db, base_price_paise=10_000, duration_days=365)
    h = auth_header(client, user.email)

    # First purchase.
    r = client.post("/api/v1/payments/orders", headers=h,
                    json={"plan_slug": "exam-bundle"})
    oid1 = r.json()["order_id"]
    client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid1, "payment_id": "p1",
        "signature": f"sig:{oid1}:p1"})
    sub_after_1 = (db.query(Subscription)
                   .filter_by(user_id=user.id, plan_id=plan.id).first())
    first_expiry = sub_after_1.expires_at

    # Second purchase while still active → expiry should extend by full
    # duration on top of the existing expiry.
    r2 = client.post("/api/v1/payments/orders", headers=h,
                     json={"plan_slug": "exam-bundle"})
    oid2 = r2.json()["order_id"]
    client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid2, "payment_id": "p2",
        "signature": f"sig:{oid2}:p2"})
    db.refresh(sub_after_1)
    delta = (sub_after_1.expires_at - first_expiry).days
    assert 364 <= delta <= 366


# =================================================== webhook hardening
import json


def _captured_event(order_id: str, payment_id: str = "pay_w_1",
                     event_id: str = "evt_w_1") -> dict:
    """Shape of a Razorpay 'payment.captured' webhook payload."""
    return {
        "id": event_id,
        "event": "payment.captured",
        "payload": {
            "payment": {"entity": {
                "id": payment_id, "order_id": order_id, "status": "captured",
            }},
        },
    }


def _failed_event(order_id: str, event_id: str = "evt_w_2") -> dict:
    return {
        "id": event_id,
        "event": "payment.failed",
        "payload": {
            "payment": {"entity": {
                "id": "pay_w_failed", "order_id": order_id, "status": "failed",
            }},
        },
    }


def _post_webhook(client, event: dict):
    return client.post("/api/v1/payments/webhook",
                       data=json.dumps(event),
                       headers={"X-Razorpay-Signature": "fake-webhook-sig",
                                 "Content-Type": "application/json"})


def test_webhook_payment_captured_activates_subscription_without_verify(
        client, db, user, fake_provider):
    """Dropped-tab scenario: order created, user closes browser before
    /verify fires. Webhook must still grant access."""
    plan = _seed_plan(db, base_price_paise=10_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h,
                    json={"plan_slug": "exam-bundle"})
    oid = r.json()["order_id"]

    # No /verify call — user closed the tab.
    r2 = _post_webhook(client, _captured_event(oid))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["action"] == "activated"

    sub = (db.query(Subscription)
           .filter_by(user_id=user.id, plan_id=plan.id, status="active")
           .first())
    assert sub is not None
    assert sub.expires_at is not None


def test_webhook_after_verify_is_a_no_op(client, db, user, fake_provider):
    """Verify already activated → webhook arriving second changes nothing.
    No duplicate Subscription, no duplicate OfferRedemption."""
    _seed_plan(db, base_price_paise=10_000)
    db.add(OfferCode(code="STACK", discount_type="percent",
                     discount_value=10, is_active=True))
    db.commit()
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "offer_code": "stack"})
    oid = r.json()["order_id"]

    # Step 1: verify activates.
    client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid, "payment_id": "p1",
        "signature": f"sig:{oid}:p1"})
    subs_before = db.query(Subscription).filter_by(user_id=user.id).count()
    redemptions_before = db.query(OfferRedemption).count()

    # Step 2: webhook arrives later — should be a no-op.
    r2 = _post_webhook(client, _captured_event(oid, payment_id="p1"))
    assert r2.status_code == 200

    assert db.query(Subscription).filter_by(user_id=user.id).count() == subs_before
    assert db.query(OfferRedemption).count() == redemptions_before


def test_webhook_duplicate_event_id_is_ignored(client, db, user, fake_provider):
    """Razorpay retries webhooks. Same event_id arriving twice must
    only be processed once."""
    _seed_plan(db, base_price_paise=10_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h,
                    json={"plan_slug": "exam-bundle"})
    oid = r.json()["order_id"]

    r1 = _post_webhook(client, _captured_event(oid, event_id="evt_dup"))
    assert r1.status_code == 200
    r2 = _post_webhook(client, _captured_event(oid, event_id="evt_dup"))
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True


def test_webhook_payment_failed_releases_offer_seat(
        client, db, user, fake_provider):
    """payment.failed must roll back the redemption seat the order-create
    reserved. Otherwise capped offers leak inventory on failed payments."""
    _seed_plan(db, base_price_paise=10_000)
    db.add(OfferCode(code="ONCE", discount_type="percent",
                     discount_value=10,
                     max_redemptions=1, used_count=0, is_active=True))
    db.commit()
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "offer_code": "once"})
    oid = r.json()["order_id"]
    code = db.query(OfferCode).filter_by(code="ONCE").first()
    assert code.used_count == 1, "order-create should have reserved the seat"

    r2 = _post_webhook(client, _failed_event(oid))
    assert r2.status_code == 200
    assert r2.json()["action"] == "failed"

    db.refresh(code)
    assert code.used_count == 0, "failed payment should release the seat"

    pay = db.query(Payment).filter_by(provider_order_id=oid).first()
    assert pay.status == "failed"


def test_webhook_unknown_order_persists_event_but_does_nothing(
        client, db, fake_provider):
    """A webhook for an order we don't know about (e.g. arrived before
    our DB write committed, or for a different merchant) shouldn't
    crash. Persist for audit, take no state action."""
    r = _post_webhook(client, _captured_event("order_does_not_exist"))
    assert r.status_code == 200
    assert r.json()["action"] == "ignored"
    assert db.query(WebhookEvent).count() == 1


def test_webhook_invalid_signature_400(client, db, fake_provider):
    """Anything posted to /webhook without a matching HMAC is rejected
    before parsing — protects against spoofed events."""
    r = client.post("/api/v1/payments/webhook",
                    data=json.dumps({"id": "x", "event": "payment.captured"}),
                    headers={"X-Razorpay-Signature": "wrong",
                              "Content-Type": "application/json"})
    assert r.status_code == 400


def test_verify_after_webhook_activated_returns_active(
        client, db, user, fake_provider):
    """If webhook beats verify (rare but possible), verify must still
    return a successful 200 with the existing subscription's expiry —
    otherwise the frontend would show an error and the user wouldn't
    redirect to /exams."""
    plan = _seed_plan(db, base_price_paise=10_000)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h,
                    json={"plan_slug": "exam-bundle"})
    oid = r.json()["order_id"]

    # Webhook arrives first.
    _post_webhook(client, _captured_event(oid))

    # Then verify catches up.
    r2 = client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": oid, "payment_id": "p1",
        "signature": f"sig:{oid}:p1"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "active"
    assert body["plan_slug"] == "exam-bundle"


# ============================================================ currencies
# International currency in /payments/orders + Razorpay handoff.
# Uses the new live-FX system (pricing.fx_live_raw + markup).

from datetime import datetime, timezone


@pytest.fixture
def fx_live_settings(monkeypatch):
    """Live FX rates + 5% markup + 18% GST + stack-off."""
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent":               18,
            "pricing.fx_live_raw":               {"USD": 83.33, "EUR": 90.91},
            "pricing.fx_live_fetched_at":        fresh,
            "pricing.fx_markup_percent":         5.0,
            "pricing.fx_overrides":              {},
        }.get(k, default))


def test_order_in_usd_passes_total_to_provider(
        client, db, user, fake_provider, fx_live_settings):
    """Razorpay gets the USD TOTAL (subtotal + 5% markup, ceiled to
    next whole unit), NOT INR paise.

    Whole-unit ceil is Razorpay-International's integer-amount rule —
    GBP confirmed in prod that fractional charges silently rounded up
    on their end, breaking the displayed-vs-charged contract."""
    import math
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 201, r.text
    body = r.json()

    expected_sub = round(99900 / 83.33)
    expected_markup = round(expected_sub * 5.0 / 100.0)
    pre_round = expected_sub + expected_markup
    expected_total = math.ceil(pre_round / 100) * 100   # ceil to whole unit

    assert body["currency"] == "USD"
    assert body["amount"] == expected_total
    assert body["amount"] % 100 == 0                # always a whole unit
    assert fake_provider.last_order_amount == expected_total

    # INR breakdown still shown (for receipts / reference).
    assert body["base_amount"] == 99900
    assert body["subtotal_amount"] == 99900
    assert body["final_inr_paise"] == 117882   # subtotal + 18% GST INR-side
    # GST is zeroed in the chargeable amount (international customer).
    assert body["gst_amount"] == 0


def test_order_in_inr_unchanged_existing_behavior(
        client, db, user, fake_provider, fx_live_settings):
    """REGRESSION GUARD: INR / no-currency → unchanged behavior (paise,
    full GST included in charge)."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle"})   # no currency → defaults INR
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["currency"] == "INR"
    assert body["amount"] == 117882
    assert fake_provider.last_order_amount == 117882
    assert body["gst_amount"] == 17982


def test_order_with_unsupported_currency_400(
        client, db, user, fake_provider, fx_live_settings):
    """REJECT unsupported currencies at order-create time (different
    from /pricing/quote which falls back to INR display)."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "currency": "JPY"})
    assert r.status_code == 400, r.text
    assert "not supported" in r.json()["error"]["message"].lower()


def test_order_in_eur_persists_currency_on_payment_row(
        client, db, user, fake_provider, fx_live_settings):
    """The Payment row stores the charge currency (and total, post
    whole-unit ceil) so admin can later reconcile EUR orders."""
    import math
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "currency": "EUR"})
    assert r.status_code == 201
    pay = (db.query(Payment).filter_by(provider_order_id=r.json()["order_id"])
           .first())
    assert pay.currency == "EUR"
    expected_sub = round(99900 / 90.91)
    expected_markup = round(expected_sub * 5.0 / 100.0)
    expected_total = math.ceil((expected_sub + expected_markup) / 100) * 100
    assert pay.amount_paise == expected_total
    assert pay.amount_paise % 100 == 0


def test_order_with_admin_override_skips_markup(client, db, user,
                                                 fake_provider, monkeypatch):
    """Admin override → admin's rate is the final rate, no markup added.
    Whole-unit ceil still applies (Razorpay-rail constraint is independent
    of whether the rate came from live data or an override)."""
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent":               0,
            "pricing.fx_live_raw":               {"USD": 83.33},
            "pricing.fx_live_fetched_at":        fresh,
            "pricing.fx_markup_percent":         5.0,
            "pricing.fx_overrides":              {"USD": 90.0},  # override wins
        }.get(k, default))

    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 201
    # 99900 / 90 = 1110 cents, ceiled to 1200 cents = $12.00.
    # No markup line (admin's rate is final), but rounding still applies.
    assert r.json()["amount"] == 1200
    assert r.json()["amount"] % 100 == 0


# ====================================================== PayPal currency routing
# PayPal-rail tests use a separate fake provider with name="paypal" so
# the new currency-routing in PaymentRegistry / provider_name dispatch
# in /verify + /paypal/capture exercise the right code paths.


class FakePayPal:
    """Same surface as PayPalProvider but no network. Distinct from
    FakeProvider above (which poses as Razorpay) so we can pin the
    currency-routing path without the test fixtures bleeding into
    each other."""
    name = "paypal"; key_id = "AcDe-PayPalClient"; mode = "test"

    def __init__(self):
        self.last_order_amount = None
        self.last_currency = None
        self.last_return_url = None
        self._captures: dict[str, dict] = {}

    def create_order(self, amount_minor, receipt=None, currency="USD",
                     return_url=None, cancel_url=None):
        self.last_order_amount = amount_minor
        self.last_currency = currency
        self.last_return_url = return_url
        oid = f"PP-ORDER-{receipt or 'test'}"
        # Pre-cache a happy-path capture for this order so the capture
        # endpoint can return realistic data later.
        self._captures[oid] = {
            "order_id": oid, "capture_id": f"PP-CAP-{oid}",
            "status": "COMPLETED",
            "amount_minor": amount_minor, "currency": currency,
        }
        return {
            "id": oid, "amount": amount_minor, "currency": currency,
            "status": "CREATED",
            "approval_url": f"https://sandbox.paypal.com/approve?token={oid}",
        }

    def capture_order(self, order_id):
        # Return the canned capture; raise if unknown to mirror real
        # PayPal's 422 ORDER_NOT_FOUND for sanity.
        cap = self._captures.get(order_id)
        if not cap:
            from app.core.exceptions import AppError
            raise AppError("PayPal: order not found", status_code=502)
        return cap

    def verify_webhook(self, headers, body):
        # Tests pass a marker header to opt-in to "valid" verification
        # without round-tripping a mocked PayPal verify-signature call.
        return headers.get("x-test-paypal-valid") == "1"

    def verify_payment_signature(self, *_args, **_kw):
        return False   # PayPal doesn't use this code path

    def verify_webhook_signature(self, *_args, **_kw):
        return False   # Razorpay-shape verifier, intentionally rejects


@pytest.fixture
def paypal_settings(monkeypatch):
    """Live FX + non-INR routing pointed at the fake PayPal."""
    fresh = datetime.now(timezone.utc).isoformat()
    from app.core import settings_store as ss_module
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent":               18,
            "pricing.fx_live_raw":               {"USD": 83.33, "GBP": 105.0},
            "pricing.fx_live_fetched_at":        fresh,
            "pricing.fx_markup_percent":         5.0,
            "pricing.fx_overrides":              {},
            # Both INR and non-INR rails configured (different IDs so
            # the registry distinguishes them when get_for_currency
            # routes by currency).
            "payment.active_provider_id":        1,
            "payment.non_inr_provider_id":       2,
        }.get(k, default))


@pytest.fixture
def mixed_providers(monkeypatch, paypal_settings):
    """Two providers active: Razorpay (INR) + PayPal (non-INR).
    PaymentRegistry.get_for_currency dispatches between them by ISO code."""
    razorpay = FakeProvider()
    paypal = FakePayPal()

    def by_id(cls, provider_id):
        # active_provider_id=1 → razorpay; non_inr_provider_id=2 → paypal.
        return razorpay if provider_id == 1 else paypal

    def by_ccy(cls, ccy):
        return razorpay if (ccy or "INR").upper() == "INR" else paypal

    monkeypatch.setattr(PaymentRegistry, "get_active",
                        classmethod(lambda cls: razorpay))
    monkeypatch.setattr(PaymentRegistry, "get_by_id", classmethod(by_id))
    monkeypatch.setattr(PaymentRegistry, "get_for_currency",
                        classmethod(by_ccy))
    return {"razorpay": razorpay, "paypal": paypal}


def test_inr_order_still_routes_to_razorpay(
        client, db, user, mixed_providers):
    """REGRESSION GUARD: INR orders MUST stay on the Razorpay rail
    even with PayPal configured for non-INR. Routing must not bleed."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "exam-bundle"})   # default INR
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "razorpay"
    assert body["razorpay_key_id"] == "rzp_test_fake"
    # PayPal fields stay null on a Razorpay-rail order.
    assert body["paypal_client_id"] is None
    assert body["paypal_approval_url"] is None
    assert mixed_providers["razorpay"].last_order_amount == 99900 + 17982
    assert mixed_providers["paypal"].last_order_amount is None


def test_usd_order_routes_to_paypal_and_returns_approval_url(
        client, db, user, mixed_providers):
    """Non-INR orders land on the PayPal rail; response payload shape
    matches what the frontend redirect flow expects."""
    import math
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders",
                    headers={**h, "Origin": "https://app.example.com"},
                    json={"plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "paypal"
    assert body["razorpay_key_id"] is None
    assert body["paypal_client_id"] == "AcDe-PayPalClient"
    assert body["paypal_approval_url"].startswith("https://sandbox.paypal.com/")
    # Amount is the ceil-to-whole-unit total (Razorpay-International rule
    # still applies to the displayed price — PayPal accepts it cleanly).
    expected_sub = round(99900 / 83.33)
    expected_markup = round(expected_sub * 5.0 / 100.0)
    expected_total = math.ceil((expected_sub + expected_markup) / 100) * 100
    assert body["amount"] == expected_total
    assert body["currency"] == "USD"
    # PayPal saw the return URL derived from the request's Origin.
    assert (mixed_providers["paypal"].last_return_url
            == "https://app.example.com/payments/paypal/return")


def test_usd_order_without_origin_header_400(
        client, db, user, mixed_providers):
    """If the request didn't come from a browser (no Origin header),
    we can't build a return URL for PayPal — reject with a clear 400
    so the operator knows to check the call site."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    # Suppress the Origin TestClient adds by default by overriding it.
    r = client.post("/api/v1/payments/orders",
                    headers={**h, "Origin": ""},
                    json={"plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 400
    assert "Origin" in r.json()["error"]["message"]


def test_non_inr_provider_unconfigured_503(client, db, user, monkeypatch):
    """If the admin hasn't configured a non-INR provider yet, non-INR
    orders should 503 with a clear pointer to /admin/payment-providers
    rather than silently falling through to the INR provider.

    This test does NOT use the fake_provider fixture — it exercises
    the REAL PaymentRegistry.get_for_currency code path so the
    unconfigured-503 branch fires."""
    from app.core import settings_store as ss_module
    fresh = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(ss_module.SettingsStore, "get",
        lambda self, k, default=None: {
            "pricing.stack_offer_with_discount": False,
            "pricing.gst_percent":               18,
            "pricing.fx_live_raw":               {"USD": 83.33},
            "pricing.fx_live_fetched_at":        fresh,
            "pricing.fx_markup_percent":         5.0,
            "pricing.fx_overrides":              {},
            # payment.active_provider_id stays None too (we don't even
            # reach the INR-rail lookup — routing rejects on USD first).
        }.get(k, default))
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders",
                    headers={**h, "Origin": "https://app.example.com"},
                    json={"plan_slug": "exam-bundle", "currency": "USD"})
    assert r.status_code == 503, r.text
    assert "non-INR payment provider" in r.json()["error"]["message"]


def test_paypal_capture_activates_subscription(
        client, db, user, mixed_providers):
    """The frontend Smart-Button-onApprove / return-page flow hits
    /payments/paypal/capture with the order_id. On COMPLETED status
    we activate the subscription same as Razorpay's /verify path.

    Idempotency: calling capture again returns "active" again (the
    activation function short-circuits on already-set subscription_id)."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    create = client.post("/api/v1/payments/orders",
                          headers={**h, "Origin": "https://app.example.com"},
                          json={"plan_slug": "exam-bundle", "currency": "USD"})
    assert create.status_code == 201
    order_id = create.json()["order_id"]

    cap = client.post("/api/v1/payments/paypal/capture", headers=h,
                       json={"order_id": order_id})
    assert cap.status_code == 200, cap.text
    body = cap.json()
    assert body["status"] == "active"
    assert body["plan_slug"] == "exam-bundle"
    # The Payment row got provider_payment_id (the capture id) set.
    pay = (db.query(Payment).filter_by(provider_order_id=order_id).first())
    assert pay.status == "captured"
    assert pay.provider_name == "paypal"
    assert pay.provider_payment_id == f"PP-CAP-{order_id}"


def test_paypal_capture_rejects_razorpay_order(
        client, db, user, mixed_providers):
    """A buyer can't accidentally (or maliciously) submit a Razorpay
    order_id to the PayPal capture endpoint and back-door an INR
    payment through the wrong code path."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    rzp_create = client.post("/api/v1/payments/orders",
                              headers=h, json={"plan_slug": "exam-bundle"})
    razorpay_order_id = rzp_create.json()["order_id"]

    cap = client.post("/api/v1/payments/paypal/capture", headers=h,
                       json={"order_id": razorpay_order_id})
    assert cap.status_code == 400
    assert "razorpay" in cap.json()["error"]["message"].lower()


def test_verify_rejects_paypal_order(
        client, db, user, mixed_providers):
    """Symmetric guard: a PayPal order can't slip through Razorpay's
    /verify endpoint (which uses HMAC signature verification)."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    pp_create = client.post("/api/v1/payments/orders",
                             headers={**h, "Origin": "https://app.example.com"},
                             json={"plan_slug": "exam-bundle", "currency": "USD"})
    paypal_order_id = pp_create.json()["order_id"]

    v = client.post("/api/v1/payments/verify", headers=h, json={
        "order_id": paypal_order_id,
        "payment_id": "fake",
        "signature": "fake"})
    assert v.status_code == 400
    assert "paypal" in v.json()["error"]["message"].lower()


def test_paypal_webhook_activates_on_capture_completed(
        client, db, user, mixed_providers):
    """Out-of-band webhook flow (dropped browser tab between PayPal
    approval and our /paypal/capture call). Webhook activates the
    subscription via the same lifecycle function."""
    _seed_plan(db, base_price_paise=99900)
    h = auth_header(client, user.email)
    create = client.post("/api/v1/payments/orders",
                          headers={**h, "Origin": "https://app.example.com"},
                          json={"plan_slug": "exam-bundle", "currency": "USD"})
    order_id = create.json()["order_id"]

    event = {
        "id": "WH-EVT-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": f"PP-CAP-{order_id}",
            "status": "COMPLETED",
            "supplementary_data": {
                "related_ids": {"order_id": order_id}},
        },
    }
    r = client.post("/api/v1/payments/paypal/webhook",
                    data=json.dumps(event),
                    headers={"content-type": "application/json",
                              "x-test-paypal-valid": "1"})
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "activated"
    pay = (db.query(Payment).filter_by(provider_order_id=order_id).first())
    assert pay.status == "captured"
    assert pay.provider_payment_id == f"PP-CAP-{order_id}"


def test_paypal_webhook_rejects_unverified(
        client, db, user, mixed_providers):
    """Inbound webhook without the verify-signature marker → 400.
    Real-world equivalent: PayPal's verify-signature API returned
    FAILURE, or required transmission headers missing."""
    event = {"id": "WH-EVT-X", "event_type": "PAYMENT.CAPTURE.COMPLETED",
             "resource": {}}
    r = client.post("/api/v1/payments/paypal/webhook",
                    data=json.dumps(event),
                    headers={"content-type": "application/json"})
    assert r.status_code == 400
