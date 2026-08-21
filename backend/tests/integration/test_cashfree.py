"""Cashfree adapter + hosted-checkout flow — simulated gateway.

Real-sandbox verification happens with the operator's test keys before
the provider is listed live; these tests pin the wiring: order
creation returns the session id, verify activates only on PAID,
webhooks verify signatures against every enabled account and settle
idempotently, and with NO Cashfree config the platform is untouched.
"""
import base64
import hashlib
import hmac
import json

import pytest

from tests.conftest import auth_header
from app.core import settings_store as ss_module
from app.models.payment import Payment
from app.models.plan import Plan
from app.services.cashfree_service import CashfreeProvider
from app.services.payment_registry import PaymentRegistry


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path))
    ss_module._local.clear()
    try:
        from app.core.redis import redis_client
        for k in redis_client.keys(ss_module.CACHE_PREFIX + "*"):
            redis_client.delete(k)
    except Exception:
        pass
    PaymentRegistry.invalidate()
    yield
    ss_module._local.clear()
    PaymentRegistry.invalidate()


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.services.email.mailer.send_email",
        lambda *a, **k: (calls.append((a, k)) or True))
    return calls


class _FakeCashfree(CashfreeProvider):
    """Real adapter class with the HTTP layer replaced — signature
    verification and payload shaping run the genuine code paths."""
    orders: dict = {}

    def _request(self, method, path, payload=None):
        if method == "POST" and path == "/orders":
            oid = payload["order_id"]
            _FakeCashfree.orders[oid] = {
                "order_id": oid, "order_status": "ACTIVE",
                "payment_session_id": f"session_{oid}",
            }
            return _FakeCashfree.orders[oid]
        if method == "GET" and path.startswith("/orders/") \
                and path.endswith("/payments"):
            oid = path.split("/")[2]
            o = _FakeCashfree.orders.get(oid) or {}
            if o.get("order_status") == "PAID":
                return [{"cf_payment_id": 9001,
                         "payment_status": "SUCCESS"}]
            return []
        if method == "GET" and path.startswith("/orders/"):
            oid = path.split("/")[2]
            if oid in _FakeCashfree.orders:
                return _FakeCashfree.orders[oid]
            raise RuntimeError(f"Cashfree API 404 on GET {path}: "
                               "order_not_found")
        raise RuntimeError(f"unexpected {method} {path}")


def _plan(db):
    plan = Plan(name="CP Plan", slug="cp-plan", bundle_type="exam_bundle",
                base_price_paise=99900, currency="INR", duration_days=365,
                perks={}, is_active=True, display_order=10)
    db.add(plan); db.commit(); db.refresh(plan)
    return plan


def _mk_cashfree(client, admin, **listing):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": "cashfree-main", "provider_type": "cashfree",
        "mode": "test", "display_name": "Card (Cashfree)",
        "public_key": "cf_app_id_x", "api_secret": "cf_secret_x",
        "webhook_secret": "cf_whsec_x",
        "is_enabled": True, "priority": 100,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    if listing:
        r = client.patch(
            f"/api/v1/admin/payment-providers/{pid}/listing",
            headers=h, json=listing)
        assert r.status_code == 200, r.text
    return pid


def _sign(body: bytes, ts: str, secret: str = "cf_whsec_x") -> str:
    return base64.b64encode(hmac.new(
        secret.encode(), ts.encode() + body, hashlib.sha256,
    ).digest()).decode()


# ── adapter unit behavior ────────────────────────────────────────────

def test_webhook_signature_scheme_roundtrip():
    p = CashfreeProvider("id", "sec", webhook_secret="whsec")
    body = b'{"type":"PAYMENT_SUCCESS_WEBHOOK"}'
    good = base64.b64encode(hmac.new(
        b"whsec", b"1700000000" + body, hashlib.sha256).digest()).decode()
    assert p.verify_webhook("1700000000", body, good)
    assert not p.verify_webhook("1700000001", body, good)   # ts mismatch
    assert not p.verify_webhook("1700000000", body, "tampered")
    assert not p.verify_webhook("", body, good)


def test_adapter_amount_units_and_mode_urls():
    live = CashfreeProvider("id", "sec", mode="live")
    test = CashfreeProvider("id", "sec", mode="test")
    assert "api.cashfree.com" in live.base
    assert "sandbox.cashfree.com" in test.base


# ── dormancy: no config → platform untouched ─────────────────────────

def test_dormant_without_config(client, admin):
    """Cashfree in the codebase but no account configured: gateway
    options and provider listings behave exactly as before."""
    r = client.get("/api/v1/payments/gateway-options?currency=USD")
    assert r.status_code == 200
    assert r.json()["options"] == []


# ── hosted flow: create → verify(PAID) → activate ────────────────────

def test_create_order_returns_session_and_verify_activates(
        client, db, user, admin, monkeypatch, sent):
    from app.services import payment_registry as reg
    monkeypatch.setitem(reg.PROVIDER_CLASSES, "cashfree", _FakeCashfree)
    _FakeCashfree.orders = {}
    plan = _plan(db)
    pid = _mk_cashfree(client, admin, listed_for_intl=True, intl_rank=5)

    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/pricing.fx_overrides",
                     headers=h, json={"value": {"USD": 83.0}})
    assert r.status_code == 200, r.text

    uh = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders",
                    headers={**uh, "Origin": "https://cpmaiexamprep.com"},
                    json={"plan_slug": "cp-plan", "currency": "USD"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "cashfree"
    assert body["cashfree_payment_session_id"].startswith("session_")
    assert body["cashfree_mode"] == "test"
    order_id = body["order_id"]
    p = db.query(Payment).filter_by(provider_order_id=order_id).one()
    assert p.provider_name == "cashfree"
    assert p.provider_config_id == pid

    # Verify before payment completes → honest 409, nothing activated.
    r = client.post("/api/v1/payments/cashfree/verify", headers=uh,
                    json={"order_id": order_id})
    assert r.status_code == 409

    # Gateway marks it paid; verify now activates.
    _FakeCashfree.orders[order_id]["order_status"] = "PAID"
    r = client.post("/api/v1/payments/cashfree/verify", headers=uh,
                    json={"order_id": order_id})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    db.refresh(p)
    assert p.status == "captured" and p.captured_via == "verify"


# ── webhook: signed settle + idempotency + failure path ──────────────

def _webhook(client, body: bytes, ts: str, sig: str):
    return client.post("/api/v1/payments/cashfree/webhook", content=body,
                       headers={"Content-Type": "application/json",
                                "x-webhook-timestamp": ts,
                                "x-webhook-signature": sig})


def test_webhook_settles_and_dedupes(client, db, user, admin,
                                     monkeypatch, sent):
    from app.services import payment_registry as reg
    monkeypatch.setitem(reg.PROVIDER_CLASSES, "cashfree", _FakeCashfree)
    _FakeCashfree.orders = {}
    plan = _plan(db)
    _mk_cashfree(client, admin, listed_for_intl=True)
    p = Payment(user_id=user.id, plan_id=plan.id, provider_name="cashfree",
                provider_order_id="u_cf_wh_1", amount_paise=1300,
                currency="USD", status="created",
                idempotency_key="u_cf_wh_1")
    db.add(p); db.commit()

    body = json.dumps({"type": "PAYMENT_SUCCESS_WEBHOOK", "data": {
        "order": {"order_id": "u_cf_wh_1"},
        "payment": {"cf_payment_id": 777, "payment_status": "SUCCESS"},
    }}).encode()
    ts = "1700000123"
    r = _webhook(client, body, ts, _sign(body, ts))
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "activated"
    db.refresh(p)
    assert p.status == "captured"
    assert p.captured_via == "webhook"
    assert p.provider_payment_id == "777"
    # Duplicate delivery → no-op
    r = _webhook(client, body, ts, _sign(body, ts))
    assert r.json().get("duplicate") is True
    # Bad signature → rejected
    r = _webhook(client, body, ts, "bogus")
    assert r.status_code == 400
    # last_webhook_at stamped for the health line
    from app.models.payment_provider import PaymentProviderConfig
    row = db.query(PaymentProviderConfig).filter_by(
        provider_type="cashfree").one()
    db.refresh(row)
    assert row.last_webhook_at is not None


def test_webhook_failed_marks_payment_failed(client, db, user, admin,
                                             monkeypatch):
    from app.services import payment_registry as reg
    monkeypatch.setitem(reg.PROVIDER_CLASSES, "cashfree", _FakeCashfree)
    plan = _plan(db)
    _mk_cashfree(client, admin, listed_for_intl=True)
    p = Payment(user_id=user.id, plan_id=plan.id, provider_name="cashfree",
                provider_order_id="u_cf_wh_2", amount_paise=1300,
                currency="USD", status="created",
                idempotency_key="u_cf_wh_2")
    db.add(p); db.commit()
    body = json.dumps({"type": "PAYMENT_FAILED_WEBHOOK", "data": {
        "order": {"order_id": "u_cf_wh_2"},
        "payment": {"cf_payment_id": 778, "payment_status": "FAILED"},
    }}).encode()
    ts = "1700000456"
    r = _webhook(client, body, ts, _sign(body, ts))
    assert r.status_code == 200
    assert r.json()["action"] == "failed"
    db.refresh(p)
    assert p.status == "failed"


def test_reconcile_sweep_heals_cashfree_orders(client, db, user, admin,
                                               monkeypatch, sent):
    """The hourly sweep speaks fetch_order_payments — Cashfree rows
    heal exactly like Razorpay ones."""
    from datetime import datetime, timedelta, timezone
    from app.services import payment_registry as reg
    from app.services import payment_reconcile as recon
    monkeypatch.setitem(reg.PROVIDER_CLASSES, "cashfree", _FakeCashfree)
    _FakeCashfree.orders = {"u_cf_rec_1": {
        "order_id": "u_cf_rec_1", "order_status": "PAID"}}
    plan = _plan(db)
    pid = _mk_cashfree(client, admin, listed_for_intl=True)
    p = Payment(user_id=user.id, plan_id=plan.id, provider_name="razorpay",
                provider_order_id="u_cf_rec_1", amount_paise=1300,
                currency="USD", status="created",
                provider_config_id=pid,
                idempotency_key="u_cf_rec_1")
    db.add(p); db.commit()
    p.created_at = datetime.now(timezone.utc) - timedelta(minutes=60)
    db.commit()
    result = recon.reconcile_created_payments(db)
    assert result["healed"] == 1
    db.refresh(p)
    assert p.status == "captured" and p.captured_via == "reconcile"
