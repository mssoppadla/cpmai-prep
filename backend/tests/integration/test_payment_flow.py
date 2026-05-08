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
from app.models.payment import Payment
from app.services.payment_registry import PaymentRegistry
from tests.conftest import auth_header


# ----------------------------------------------------------- fake provider
class FakeProvider:
    """Same surface as RazorpayProvider but no network."""
    name = "fake"; key_id = "rzp_test_fake"; mode = "test"

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
    p = FakeProvider()
    monkeypatch.setattr(PaymentRegistry, "get_active", classmethod(lambda cls: p))
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
    pay = (db.query(Payment).filter_by(razorpay_order_id=r.json()["order_id"])
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
