"""Payments ops hygiene — refunds, ad-hoc invoices, traceability,
webhook health, reconciliation sweep (migration 0049 release)."""
import pytest

from tests.conftest import auth_header
from app.core import settings_store as ss_module
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.services import invoice as invoice_module


@pytest.fixture(autouse=True)
def _ops_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path))
    ss_module._local.clear()
    try:
        from app.core.redis import redis_client
        for k in redis_client.keys(ss_module.CACHE_PREFIX + "*"):
            redis_client.delete(k)
    except Exception:
        pass
    yield
    ss_module._local.clear()


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    def _fake_send(to, subject, html_body, attachments=None, cc=None):
        calls.append({"to": to, "subject": subject, "html": html_body,
                      "attachments": attachments or [], "cc": cc})
        return True

    monkeypatch.setattr("app.services.email.mailer.send_email", _fake_send)
    return calls


@pytest.fixture
def sync_queue(monkeypatch, db):
    def _sync(payment_id):
        p = db.get(Payment, payment_id)
        if p is not None:
            invoice_module.send_invoice_email(db, p, force=True)
    monkeypatch.setattr(invoice_module, "queue_invoice_email", _sync)
    return _sync


def _plan(db):
    plan = Plan(name="CP Plan", slug="cp-plan", bundle_type="exam_bundle",
                base_price_paise=99900, currency="INR", duration_days=365,
                perks={}, is_active=True, display_order=10)
    db.add(plan); db.commit(); db.refresh(plan)
    return plan


def _payment(db, user, plan, **kw):
    defaults = dict(user_id=user.id, plan_id=plan.id,
                    provider_name="razorpay",
                    provider_order_id=f"order_ops_{user.id}_{plan.id}",
                    amount_paise=99900, currency="INR", status="created",
                    idempotency_key=f"idem_ops_{user.id}_{plan.id}")
    defaults.update(kw)
    p = Payment(**defaults)
    db.add(p); db.commit(); db.refresh(p)
    return p


# ── refunds ──────────────────────────────────────────────────────────

def test_mark_refunded_with_revoke(client, db, user, admin, sent,
                                   sync_queue):
    plan = _plan(db)
    p = _payment(db, user, plan)
    h = auth_header(client, admin.email)
    r = client.post(f"/api/v1/admin/payments/{p.id}/mark-paid", headers=h)
    assert r.status_code == 200
    db.refresh(p)
    r = client.post(f"/api/v1/admin/payments/{p.id}/mark-refunded",
                    headers=h, json={"reason": "customer requested",
                                     "revoke_subscription": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "refunded", "subscription_revoked": True}
    db.refresh(p)
    assert p.status == "refunded"
    sub = db.get(Subscription, p.subscription_id)
    assert sub.revoked_at is not None
    assert "refund" in (sub.revoke_reason or "")


def test_mark_refunded_without_revoke_keeps_access(client, db, user,
                                                   admin, sent, sync_queue):
    plan = _plan(db)
    p = _payment(db, user, plan)
    h = auth_header(client, admin.email)
    client.post(f"/api/v1/admin/payments/{p.id}/mark-paid", headers=h)
    r = client.post(f"/api/v1/admin/payments/{p.id}/mark-refunded",
                    headers=h, json={"reason": "goodwill partial refund"})
    assert r.status_code == 200
    db.refresh(p)
    sub = db.get(Subscription, p.subscription_id)
    assert sub.revoked_at is None            # access retained


def test_mark_refunded_guards(client, db, user, admin):
    plan = _plan(db)
    p = _payment(db, user, plan, status="created")
    h = auth_header(client, admin.email)
    # Not captured → 422
    assert client.post(f"/api/v1/admin/payments/{p.id}/mark-refunded",
                       headers=h, json={"reason": "nope"}
                       ).status_code == 422
    p.status = "refunded"; db.commit()
    # Idempotent on already-refunded
    r = client.post(f"/api/v1/admin/payments/{p.id}/mark-refunded",
                    headers=h, json={"reason": "again"})
    assert r.status_code == 200 and r.json()["already"] is True


# ── traceability ─────────────────────────────────────────────────────

def test_mark_paid_records_gateway_reference_and_via(client, db, user,
                                                     admin, sent,
                                                     sync_queue):
    plan = _plan(db)
    p = _payment(db, user, plan, status="failed")
    h = auth_header(client, admin.email)
    r = client.post(f"/api/v1/admin/payments/{p.id}/mark-paid", headers=h,
                    json={"gateway_reference": "pay_TQgfhrTMSKGJPZ"})
    assert r.status_code == 200, r.text
    db.refresh(p)
    assert p.provider_payment_id == "pay_TQgfhrTMSKGJPZ"
    assert p.captured_via == "admin"


def test_manual_grant_reference_and_manual_filter(client, db, user, admin,
                                                  sent, sync_queue):
    plan = _plan(db)
    h = auth_header(client, admin.email)
    r = client.post(f"/api/v1/admin/users/{user.id}/subscriptions",
                    headers=h, json={
                        "plan_id": plan.id, "period_days": 30,
                        "reason": "paypal accepted manually",
                        "record_payment": True,
                        "gateway_reference": "8XY12345AB678901C",
                    })
    assert r.status_code == 201, r.text
    p = db.query(Payment).filter_by(provider_name="manual").one()
    assert p.captured_via == "manual"
    assert p.provider_payment_id == "8XY12345AB678901C"
    # manual_only filter finds it; organic-only view excludes it.
    rows = client.get("/api/v1/admin/payments?manual_only=true",
                      headers=h).json()
    assert [i["id"] for i in rows["items"]] == [p.id]
    assert rows["items"][0]["captured_via"] == "manual"


def test_organic_captures_stamp_verify_and_webhook(client, db, user, admin,
                                                   sent, sync_queue,
                                                   monkeypatch):
    """verify → 'verify'; second channel never overwrites the first."""
    from app.services.payment_lifecycle import (
        activate_subscription_for_payment,
    )
    plan = _plan(db)
    p = _payment(db, user, plan)
    activate_subscription_for_payment(db, p, captured_via="verify")
    activate_subscription_for_payment(db, p, captured_via="webhook")
    db.refresh(p)
    assert p.captured_via == "verify"


# ── ad-hoc invoices ──────────────────────────────────────────────────

def test_adhoc_invoice_create_pdf_and_email(client, db, admin, sent):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/invoices/adhoc", headers=h, json={
        "buyer_name": "Geethu Rs",
        "buyer_email": "rsgeethu1986@gmail.com",
        "description": "Live CPMAI Classes — Aug batch (offline payment)",
        "amount_minor": 9912, "currency": "INR",
        "gateway_reference": "UPI-RRN-913413077065",
        "send_email": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["invoice_number"].startswith("INV-")
    assert "-M" in body["invoice_number"]     # separate manual series
    assert body["email_sent"] is True and body["email_status"] == "sent"
    assert len(sent) == 1 and sent[0]["to"] == "rsgeethu1986@gmail.com"
    assert sent[0]["attachments"][0]["filename"].endswith(".pdf")

    # PDF downloads and is a real PDF
    pdf = client.get(f"/api/v1/admin/invoices/adhoc/{body['id']}/pdf",
                     headers=h)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")

    # Listed
    lst = client.get("/api/v1/admin/invoices/adhoc", headers=h).json()
    assert lst["total"] == 1
    assert lst["items"][0]["invoice_number"] == body["invoice_number"]


def test_adhoc_invoice_no_email_then_send_later(client, db, admin, sent):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/invoices/adhoc", headers=h, json={
        "buyer_name": "Mike Lam", "buyer_email": "mike.coco@gmail.com",
        "description": "CPMAI Exam Bundle", "amount_minor": 17000,
        "currency": "HKD",
    })
    assert r.status_code == 201
    assert sent == []
    iid = r.json()["id"]
    r = client.post(f"/api/v1/admin/invoices/adhoc/{iid}/send", headers=h)
    assert r.status_code == 200 and r.json()["sent"] is True
    assert len(sent) == 1


def test_adhoc_invoice_validation(client, admin):
    h = auth_header(client, admin.email)
    bad = client.post("/api/v1/admin/invoices/adhoc", headers=h, json={
        "buyer_name": "X", "buyer_email": "not-an-email",
        "description": "abc", "amount_minor": 100,
    })
    assert bad.status_code == 422


# ── webhook health ───────────────────────────────────────────────────

def test_webhook_match_stamps_last_webhook_at(client, db, user, admin,
                                              monkeypatch, sent,
                                              sync_queue):
    import hashlib as _hl
    import hmac as _hm
    import json as _json
    from app.models.payment_provider import PaymentProviderConfig
    from app.services.payment_registry import PaymentRegistry

    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "whhealth", "provider_type": "razorpay", "mode": "test",
        "display_name": "WH Health", "public_key": "rzp_test_whhealth",
        "api_secret": "sec_whhealth", "webhook_secret": "whsec_health",
        "is_enabled": True, "priority": 100,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    PaymentRegistry.invalidate()

    plan = _plan(db)
    _payment(db, user, plan, provider_order_id="order_whh1",
             provider_config_id=pid, idempotency_key="idem_whh1")
    body = _json.dumps({"event": "payment.captured", "payload": {
        "payment": {"entity": {"id": "pay_whh1", "order_id": "order_whh1",
                               "status": "captured"}}}}).encode()
    sig = _hm.new(b"whsec_health", body, _hl.sha256).hexdigest()
    r = client.post("/api/v1/payments/webhook", content=body, headers={
        "Content-Type": "application/json",
        "X-Razorpay-Signature": sig,
        "X-Razorpay-Event-Id": "evt_whh1",
    })
    assert r.status_code == 200, r.text
    row = db.get(PaymentProviderConfig, pid)
    db.refresh(row)
    assert row.last_webhook_at is not None
    # Surface on the admin listing too
    lst = client.get("/api/v1/admin/payment-providers", headers=h).json()
    me = next(x for x in lst if x["id"] == pid)
    assert me["last_webhook_at"] is not None
    # And the captured payment is stamped 'webhook'
    pay = db.query(Payment).filter_by(provider_order_id="order_whh1").one()
    assert pay.captured_via == "webhook"


# ── reconciliation sweep ─────────────────────────────────────────────

def _mk_recon_payment(db, user, plan, order_id, minutes_old=60):
    from datetime import datetime, timedelta, timezone
    p = _payment(db, user, plan, provider_order_id=order_id,
                 idempotency_key=f"idem_{order_id}")
    p.created_at = datetime.now(timezone.utc) - timedelta(
        minutes=minutes_old)
    db.commit()
    return p


class _ReconProvider:
    """Gateway stub: knows which orders have a captured payment."""
    captured_orders: dict = {}

    def fetch_order_payments(self, order_id):
        if order_id in self.captured_orders:
            return [{"id": self.captured_orders[order_id],
                     "status": "captured"}]
        return [{"id": "pay_fail", "status": "failed"}]


def test_reconcile_heals_gateway_captured_orders(client, db, user, admin,
                                                 monkeypatch, sent,
                                                 sync_queue):
    from app.services import payment_reconcile as recon
    from app.services.payment_registry import PaymentRegistry
    plan = _plan(db)
    healed_p = _mk_recon_payment(db, user, plan, "order_recon_paid")
    missed_p = _mk_recon_payment(db, user, plan, "order_recon_unpaid")
    too_new = _mk_recon_payment(db, user, plan, "order_recon_new",
                                minutes_old=5)
    stub = _ReconProvider()
    _ReconProvider.captured_orders = {"order_recon_paid": "pay_recon1"}
    monkeypatch.setattr(PaymentRegistry, "get_for_currency",
                        classmethod(lambda cls, c: stub))
    result = recon.reconcile_created_payments(db)
    assert result["healed"] == 1 and result["checked"] == 2
    db.refresh(healed_p); db.refresh(missed_p); db.refresh(too_new)
    assert healed_p.status == "captured"
    assert healed_p.captured_via == "reconcile"
    assert healed_p.provider_payment_id == "pay_recon1"
    assert healed_p.subscription_id is not None
    assert missed_p.status == "created"
    assert too_new.status == "created"       # under the 30-min floor
    assert len(sent) == 1                    # invoice went out too


def test_reconcile_respects_kill_switch(client, db, user, admin,
                                        monkeypatch):
    from app.services import payment_reconcile as recon
    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/payments.reconcile_enabled",
                     headers=h, json={"value": False})
    assert r.status_code == 200, r.text
    plan = _plan(db)
    _mk_recon_payment(db, user, plan, "order_recon_off")
    result = recon.reconcile_created_payments(db)
    assert result == {"checked": 0, "healed": 0, "skipped": 0, "errors": 0}


def test_reconcile_row_error_is_isolated(client, db, user, admin,
                                         monkeypatch, sent, sync_queue):
    from app.services import payment_reconcile as recon
    from app.services.payment_registry import PaymentRegistry
    plan = _plan(db)
    bad = _mk_recon_payment(db, user, plan, "order_recon_err")
    good = _mk_recon_payment(db, user, plan, "order_recon_ok")

    stub = _ReconProvider()
    _ReconProvider.captured_orders = {"order_recon_ok": "pay_ok1"}
    real_fetch = stub.fetch_order_payments

    def _fetch(order_id):
        if order_id == "order_recon_err":
            raise RuntimeError("gateway 500")
        return real_fetch(order_id)
    stub.fetch_order_payments = _fetch
    monkeypatch.setattr(PaymentRegistry, "get_for_currency",
                        classmethod(lambda cls, c: stub))
    result = recon.reconcile_created_payments(db)
    assert result["errors"] == 1 and result["healed"] == 1
    db.refresh(good)
    assert good.status == "captured"
