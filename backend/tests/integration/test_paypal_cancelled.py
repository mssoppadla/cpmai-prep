"""POST /payments/paypal/cancelled — recording abandoned checkouts.

Regression guard for the 2026-07-12 UK guest-card incident: buyers who
hit PayPal's error page (or clicked cancel) left NO trace — the
Payment row sat in status='created' forever, indistinguishable from a
closed tab. Pins:

  * owner reporting a 'created' order → status becomes 'cancelled' and
    a payment.checkout_cancelled journey event is written
  * idempotent — second report is a no-op
  * NEVER downgrades captured/failed rows (late or malicious reports)
  * a reserved offer-code seat is released back to the pool
  * only the order's owner can report it; anonymous is 401
"""
from __future__ import annotations

from app.models.journey_event import JourneyEvent
from app.models.offer import OfferCode
from app.models.payment import Payment
from app.models.plan import Plan
from tests.conftest import auth_header


def _seed_payment(db, user, *, status="created", offer_code=None,
                  order_id="PAYPAL-ORDER-1") -> Payment:
    plan = Plan(name=f"Bundle {order_id}", slug=f"bundle-{order_id.lower()}",
                bundle_type="exam_bundle", base_price_paise=99900,
                currency="INR", duration_days=365, perks={},
                is_active=True, display_order=10)
    db.add(plan); db.commit(); db.refresh(plan)
    p = Payment(user_id=user.id, plan_id=plan.id, provider_name="paypal",
                provider_order_id=order_id, amount_paise=1000,
                currency="GBP", status=status,
                offer_code=offer_code,
                idempotency_key=f"idem-{order_id}")
    db.add(p); db.commit(); db.refresh(p)
    return p


def test_cancel_marks_created_order_and_emits_event(client, db, user):
    payment = _seed_payment(db, user)
    r = client.post("/api/v1/payments/paypal/cancelled",
                    headers=auth_header(client, user.email),
                    json={"order_id": "PAYPAL-ORDER-1"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    db.refresh(payment)
    assert payment.status == "cancelled"

    ev = (db.query(JourneyEvent)
          .filter(JourneyEvent.event == "payment.checkout_cancelled",
                  JourneyEvent.user_id == user.id)
          .order_by(JourneyEvent.id.desc()).first())
    assert ev is not None
    assert ev.metadata_json["provider_order_id"] == "PAYPAL-ORDER-1"


def test_cancel_is_idempotent(client, db, user):
    _seed_payment(db, user, order_id="PAYPAL-ORDER-2")
    h = auth_header(client, user.email)
    for _ in range(2):
        r = client.post("/api/v1/payments/paypal/cancelled", headers=h,
                        json={"order_id": "PAYPAL-ORDER-2"})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
    n = (db.query(JourneyEvent)
         .filter(JourneyEvent.event == "payment.checkout_cancelled")
         .count())
    assert n == 1   # second report wrote nothing


def test_cancel_never_downgrades_captured_or_failed(client, db, user):
    h = auth_header(client, user.email)
    for status, oid in (("captured", "PAYPAL-ORDER-3"),
                        ("failed", "PAYPAL-ORDER-4")):
        payment = _seed_payment(db, user, status=status, order_id=oid)
        r = client.post("/api/v1/payments/paypal/cancelled", headers=h,
                        json={"order_id": oid})
        assert r.status_code == 200
        assert r.json()["status"] == status
        db.refresh(payment)
        assert payment.status == status


def test_cancel_releases_offer_seat(client, db, user):
    offer = OfferCode(code="SAVE10", discount_type="percent",
                      discount_value=10, used_count=1, is_active=True)
    db.add(offer); db.commit()
    _seed_payment(db, user, offer_code="SAVE10", order_id="PAYPAL-ORDER-5")

    r = client.post("/api/v1/payments/paypal/cancelled",
                    headers=auth_header(client, user.email),
                    json={"order_id": "PAYPAL-ORDER-5"})
    assert r.status_code == 200
    db.refresh(offer)
    assert offer.used_count == 0


def test_cancel_requires_auth_and_ownership(client, db, user, admin):
    _seed_payment(db, user, order_id="PAYPAL-ORDER-6")
    # Anonymous → 401
    r = client.post("/api/v1/payments/paypal/cancelled",
                    json={"order_id": "PAYPAL-ORDER-6"})
    assert r.status_code == 401
    # A DIFFERENT user can't report someone else's order (404 — the
    # query is scoped to the caller).
    r = client.post("/api/v1/payments/paypal/cancelled",
                    headers=auth_header(client, admin.email),
                    json={"order_id": "PAYPAL-ORDER-6"})
    assert r.status_code == 404
