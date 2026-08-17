"""Checkout Follow-ups — GET /admin/checkout-funnel.

One screen answering "who was about to pay and didn't, and who looked
at pricing and walked away" so the operator can follow up instead of
stitching Payments + Visitor Insights by hand. Contract (spec'd before
implementation, 2026-08-16):

  - needs_followup: payments with status "failed" (any age) or
    "created" older than the abandoned threshold (15 min), newest
    first, WITH the buyer's contact details (email/name/whatsapp/
    linkedin) and plan/amount/currency. A user who LATER captured a
    payment for the same plan inside the window is excluded — they
    finished; no false alarms.
  - pricing_visitors: /pricing page.view events in the window with NO
    payment row in the window. Signed-in → contact details; anonymous
    → anon_id + geo/device so the operator can open the session
    timeline in Visitor Insights.
  - summary: visitors / started / captured counts for the window.
  - Read-only, admin-gated, window_minutes param (validated 5..43200).
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import auth_header
from app.models.journey_event import JourneyEvent
from app.models.payment import Payment
from app.models.plan import Plan

URL = "/api/v1/admin/checkout-funnel"


@pytest.fixture
def plan(db):
    p = Plan(name="Full Prep", slug="funnel-plan", description="d",
             bundle_type="exam_bundle", base_price_paise=499900,
             duration_days=180, is_active=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


def _mk_payment(db, user_id, plan_id, status, minutes_ago=30, **kw):
    oid = kw.get("order_id", f"order_{status}_{minutes_ago}")
    p = Payment(user_id=user_id, plan_id=plan_id, status=status,
                amount_paise=99900, currency=kw.get("currency", "INR"),
                provider_name=kw.get("provider_name", "razorpay"),
                idempotency_key=f"idem_{oid}",
                provider_order_id=oid)
    db.add(p)
    db.commit()
    # server_default stamps NOW; rewind explicitly for age-based cases
    p.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db.commit()
    return p


def _mk_view(db, minutes_ago=10, user_id=None, anon_id=None):
    ev = JourneyEvent(event="page.view", path="/pricing",
                      user_id=user_id, anon_id=anon_id,
                      session_id="sess-x", device="desktop",
                      country="IN", city="Bengaluru")
    db.add(ev)
    db.commit()
    ev.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db.commit()
    return ev


def test_requires_admin(client, user):
    assert client.get(URL).status_code in (401, 403)
    r = client.get(URL, headers=auth_header(client, user.email))
    assert r.status_code == 403


def test_failed_payment_listed_with_contact(client, admin, user, plan, db):
    _mk_payment(db, user.id, plan.id, "failed", minutes_ago=5)
    r = client.get(URL, headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    rows = r.json()["needs_followup"]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "failed"
    assert row["user"]["email"] == user.email
    assert row["plan_name"] == plan.name
    assert row["amount_paise"] == 99900


def test_stale_created_is_abandoned_but_fresh_created_is_not(client, admin,
                                                             user, plan, db):
    _mk_payment(db, user.id, plan.id, "created", minutes_ago=60,
                order_id="stale")
    _mk_payment(db, user.id, plan.id, "created", minutes_ago=2,
                order_id="fresh")  # still mid-checkout — not abandoned yet
    rows = client.get(URL, headers=auth_header(client, admin.email)
                      ).json()["needs_followup"]
    assert [x["provider_order_id"] for x in rows] == ["stale"]


def test_later_capture_excludes_earlier_failure(client, admin, user, plan, db):
    """Buyer failed once, then paid — nothing to follow up."""
    _mk_payment(db, user.id, plan.id, "failed", minutes_ago=40, order_id="f1")
    _mk_payment(db, user.id, plan.id, "captured", minutes_ago=20, order_id="ok")
    rows = client.get(URL, headers=auth_header(client, admin.email)
                      ).json()["needs_followup"]
    assert rows == []


def test_pricing_visitor_without_order_is_listed(client, admin, user, db):
    _mk_view(db, minutes_ago=10, user_id=user.id)
    body = client.get(URL, headers=auth_header(client, admin.email)).json()
    vs = body["pricing_visitors"]
    assert len(vs) == 1
    assert vs[0]["user"]["email"] == user.email
    assert body["summary"]["visitors"] == 1


def test_visitor_who_ordered_is_not_in_visitor_list(client, admin, user,
                                                    plan, db):
    _mk_view(db, minutes_ago=30, user_id=user.id)
    _mk_payment(db, user.id, plan.id, "captured", minutes_ago=20)
    body = client.get(URL, headers=auth_header(client, admin.email)).json()
    assert body["pricing_visitors"] == []
    assert body["summary"]["captured"] == 1


def test_anonymous_visitor_shows_anon_identity(client, admin, db):
    _mk_view(db, minutes_ago=10, anon_id="anon-abc-123")
    vs = client.get(URL, headers=auth_header(client, admin.email)
                    ).json()["pricing_visitors"]
    assert len(vs) == 1
    assert vs[0]["user"] is None
    assert vs[0]["anon_id"] == "anon-abc-123"
    assert vs[0]["country"] == "IN"


def test_window_filters_out_old_events(client, admin, user, plan, db):
    _mk_view(db, minutes_ago=300, user_id=user.id)
    _mk_payment(db, user.id, plan.id, "failed", minutes_ago=300)
    body = client.get(URL + "?window_minutes=60",
                      headers=auth_header(client, admin.email)).json()
    assert body["pricing_visitors"] == []
    assert body["needs_followup"] == []


def test_window_param_validated(client, admin):
    assert client.get(URL + "?window_minutes=1",
                      headers=auth_header(client, admin.email)).status_code == 422
    assert client.get(URL + "?window_minutes=999999",
                      headers=auth_header(client, admin.email)).status_code == 422
