"""Invoice engine — PDF generation, auto-email on capture, manual-grant
payments, admin download/resend, and the double-send guard."""
import pytest

from tests.conftest import auth_header
from app.core import settings_store as ss_module
from app.models.payment import Payment
from app.models.plan import Plan
from app.services import invoice as invoice_module
from app.services.payment_lifecycle import activate_subscription_for_payment


@pytest.fixture(autouse=True)
def _invoice_env(tmp_path, monkeypatch):
    """Isolate UPLOAD_ROOT per test and clear the settings caches
    (see test_gateway_control_plane for why both layers matter)."""
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
    """Capture outgoing invoice mails; pretend SMTP succeeded."""
    calls: list[dict] = []

    def _fake_send(to, subject, html_body, attachments=None, cc=None):
        calls.append({"to": to, "subject": subject, "html": html_body,
                      "attachments": attachments or [], "cc": cc})
        return True

    monkeypatch.setattr("app.services.email.mailer.send_email", _fake_send)
    return calls


@pytest.fixture
def sync_queue(monkeypatch, db):
    """Make queue_invoice_email synchronous (no daemon-thread race) and
    run the real send path against the test session — conftest doesn't
    patch app.core.database.SessionLocal, so the production thread body
    would otherwise hit the real DATABASE_URL. Callers import the name
    lazily inside their functions, so patching the module attribute
    covers payment_lifecycle and the grant endpoint alike."""
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
                    provider_order_id=f"order_inv_{user.id}_{plan.id}",
                    amount_paise=99900, currency="INR", status="created",
                    idempotency_key=f"idem_inv_{user.id}_{plan.id}")
    defaults.update(kw)
    p = Payment(**defaults)
    db.add(p); db.commit(); db.refresh(p)
    return p


# ── PDF generation ───────────────────────────────────────────────────

def test_ensure_invoice_pdf_assigns_number_and_writes_file(db, user):
    plan = _plan(db)
    p = _payment(db, user, plan, status="captured")
    path = invoice_module.ensure_invoice_pdf(db, p)
    assert path.exists() and path.stat().st_size > 500
    assert p.invoice_number and p.invoice_number.startswith("INV-")
    assert p.invoice_number.endswith(f"{p.id:06d}")
    # Idempotent: second call reuses number + file.
    again = invoice_module.ensure_invoice_pdf(db, p)
    assert again == path
    assert open(path, "rb").read(5) == b"%PDF-"


def test_long_plan_name_wraps_without_error(db, user):
    """Prod bug 2026-08-17: a long live-class plan name overflowed the
    description cell and overlapped the amount column. Rows now wrap via
    measured multi_cell — a very long name must still render a valid,
    larger PDF."""
    plan = Plan(name="REGISTRATION: Book Your Slot for Live CPMAI "
                     "Classes starting from 29th Aug — Zoom, evenings, "
                     "includes recordings and mock exam walkthroughs",
                slug="long-name-plan", bundle_type="live_class",
                base_price_paise=9912, currency="INR", duration_days=30,
                perks={}, is_active=True, display_order=10)
    db.add(plan); db.commit(); db.refresh(plan)
    p = _payment(db, user, plan, status="captured")
    path = invoice_module.ensure_invoice_pdf(db, p)
    assert path.exists()
    assert open(path, "rb").read(5) == b"%PDF-"
    assert path.stat().st_size > 600


def _pdf_text(path):
    from pypdf import PdfReader
    return "".join(pg.extract_text() for pg in PdfReader(str(path)).pages)


def test_inr_discount_breakdown_shown_when_consistent(db, user):
    plan = _plan(db)
    p = _payment(db, user, plan, status="captured",
                 base_amount_paise=99900, discount_paise=20000,
                 amount_paise=79900, offer_code="SAVE200")
    text = _pdf_text(invoice_module.ensure_invoice_pdf(db, p))
    assert "Discount (SAVE200)" in text
    assert "999.00 INR" in text and "799.00 INR" in text


def test_cross_currency_discount_never_mislabels_units(db, user):
    """Prod INV-2026-000083: INR-denominated base/discount rendered with
    an HKD label (5999 - 4009 "HKD" = 170 HKD). When units don't
    reconcile, only the actually-charged amount may appear, with the offer
    noted in the description."""
    plan = _plan(db)
    p = _payment(db, user, plan, status="captured", currency="HKD",
                 base_amount_paise=599900, discount_paise=400900,
                 amount_paise=17000, offer_code="EARLY")
    text = _pdf_text(invoice_module.ensure_invoice_pdf(db, p))
    assert "5999.00" not in text and "4009.00" not in text
    assert "170.00 HKD" in text
    assert "offer EARLY applied" in text


# ── auto-send on capture + double-send guard ─────────────────────────

def test_capture_sends_invoice_with_owner_cc(db, user, client, admin,
                                             sent, sync_queue):
    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/email.invoice_cc_address",
                     headers=h,
                     json={"value": "owner@example.com, books@example.com"})
    assert r.status_code == 200, r.text
    plan = _plan(db)
    p = _payment(db, user, plan)
    activate_subscription_for_payment(db, p)

    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == user.email
    # Multiple CCs pass through comma-separated (EmailMessage fans them
    # out to individual recipients at send time).
    assert mail["cc"] == "owner@example.com, books@example.com"
    assert mail["attachments"][0]["mime_type"] == "application/pdf"
    db.refresh(p)
    assert p.invoice_email_status == "sent"
    assert p.invoice_email_sent_at is not None
    assert p.invoice_number in mail["subject"]


def test_second_activation_does_not_resend(db, user, sent, sync_queue):
    plan = _plan(db)
    p = _payment(db, user, plan)
    activate_subscription_for_payment(db, p)
    activate_subscription_for_payment(db, p)   # verify-vs-webhook race
    assert len(sent) == 1


def test_invoice_disabled_setting_skips_send(db, user, client, admin,
                                             sent, sync_queue):
    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/email.invoice_enabled",
                     headers=h, json={"value": False})
    assert r.status_code == 200, r.text
    plan = _plan(db)
    p = _payment(db, user, plan)
    activate_subscription_for_payment(db, p)
    assert sent == []
    db.refresh(p)
    assert p.invoice_email_status is None


def test_smtp_failure_marks_failed_not_crash(db, user, monkeypatch,
                                             sync_queue):
    monkeypatch.setattr("app.services.email.mailer.send_email",
                        lambda *a, **k: False)
    plan = _plan(db)
    p = _payment(db, user, plan)
    sub = activate_subscription_for_payment(db, p)   # must not raise
    assert sub.status == "active"
    db.refresh(p)
    assert p.invoice_email_status == "failed"


# ── manual grant path ────────────────────────────────────────────────

def _grant(client, admin, user, plan, **extra):
    body = {"plan_id": plan.id, "period_days": 365,
            "reason": "paypal accepted manually", **extra}
    return client.post(f"/api/v1/admin/users/{user.id}/subscriptions",
                       headers=auth_header(client, admin.email), json=body)


def test_manual_grant_records_payment_and_sends_invoice(
        client, db, user, admin, sent, sync_queue):
    plan = _plan(db)
    r = _grant(client, admin, user, plan,
               record_payment=True, send_invoice=True)
    assert r.status_code == 201, r.text
    p = db.query(Payment).filter_by(user_id=user.id,
                                    provider_name="manual").one()
    assert p.status == "captured"
    assert p.amount_paise == 99900          # defaulted from plan price
    assert p.subscription_id == r.json()["id"]
    assert len(sent) == 1 and sent[0]["to"] == user.email
    db.refresh(p)
    assert p.invoice_email_status == "sent"


def test_manual_grant_without_flags_creates_no_payment_no_mail(
        client, db, user, admin, sent, sync_queue):
    plan = _plan(db)
    r = _grant(client, admin, user, plan)
    assert r.status_code == 201, r.text
    assert db.query(Payment).filter_by(user_id=user.id).count() == 0
    assert sent == []


def test_manual_grant_send_invoice_requires_record_payment(
        client, db, user, admin):
    plan = _plan(db)
    r = _grant(client, admin, user, plan, send_invoice=True)
    assert r.status_code == 422, r.text


def test_manual_grant_custom_amount_and_currency(client, db, user, admin,
                                                 sent, sync_queue):
    plan = _plan(db)
    r = _grant(client, admin, user, plan, record_payment=True,
               amount_paise=1250, currency="usd")
    assert r.status_code == 201, r.text
    p = db.query(Payment).filter_by(provider_name="manual").one()
    assert p.amount_paise == 1250 and p.currency == "USD"
    assert sent == []   # send_invoice not ticked → no invoice mail


# ── admin payments surface ───────────────────────────────────────────

def test_admin_list_shows_invoice_and_account_columns(
        client, db, user, admin, sent, sync_queue):
    plan = _plan(db)
    p = _payment(db, user, plan)
    activate_subscription_for_payment(db, p)
    r = client.get("/api/v1/admin/payments",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    row = next(i for i in r.json()["items"] if i["id"] == p.id)
    assert row["invoice_number"] == p.invoice_number
    assert row["invoice_email_status"] == "sent"
    assert row["provider_account"] == "razorpay"


def test_admin_invoice_download_and_resend(client, db, user, admin, sent):
    plan = _plan(db)
    p = _payment(db, user, plan, status="captured")
    h = auth_header(client, admin.email)
    r = client.get(f"/api/v1/admin/payments/{p.id}/invoice", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF-")

    r = client.post(f"/api/v1/admin/payments/{p.id}/invoice/send", headers=h)
    assert r.status_code == 200
    assert r.json()["sent"] is True
    assert len(sent) == 1


def test_mark_paid_captures_grants_and_invoices(client, db, user, admin,
                                                sent, sync_queue):
    """The PayPal 'waiting for acceptance' case: row failed in cpmai,
    money accepted manually at the gateway later — Mark paid must run
    the full capture path (sub + invoice email)."""
    plan = _plan(db)
    p = _payment(db, user, plan, status="failed")
    h = auth_header(client, admin.email)
    r = client.post(f"/api/v1/admin/payments/{p.id}/mark-paid", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "captured" and body["prior_status"] == "failed"
    db.refresh(p)
    assert p.status == "captured" and p.subscription_id == body["subscription_id"]
    assert len(sent) == 1, (body, p.invoice_email_status)
    assert sent[0]["to"] == user.email
    assert p.invoice_email_status == "sent"


def test_mark_paid_idempotent_and_refund_guard(client, db, user, admin,
                                               sent, sync_queue):
    plan = _plan(db)
    p = _payment(db, user, plan, status="created")
    h = auth_header(client, admin.email)
    assert client.post(f"/api/v1/admin/payments/{p.id}/mark-paid",
                       headers=h).status_code == 200
    # Second click: no duplicate invoice mail, still 200.
    assert client.post(f"/api/v1/admin/payments/{p.id}/mark-paid",
                       headers=h).status_code == 200
    assert len(sent) == 1
    p.status = "refunded"; db.commit()
    assert client.post(f"/api/v1/admin/payments/{p.id}/mark-paid",
                       headers=h).status_code == 422


def test_admin_invoice_refused_for_uncaptured(client, db, user, admin):
    plan = _plan(db)
    p = _payment(db, user, plan, status="created")
    h = auth_header(client, admin.email)
    assert client.get(f"/api/v1/admin/payments/{p.id}/invoice",
                      headers=h).status_code == 422
    assert client.post(f"/api/v1/admin/payments/{p.id}/invoice/send",
                       headers=h).status_code == 422
