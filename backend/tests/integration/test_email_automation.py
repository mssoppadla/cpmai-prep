"""Integration tests for lifecycle email automations (contract §10.2).

Covers: trigger hooks enqueue outbox rows (signup / login / payment
success / payment failed / exam submit), pay-during-wait cancellation,
send policies (once_per_user dedup, replace_pending reschedule,
every_event cooldown), the dispatcher's send-time rechecks + status/date
bookkeeping, the abandoned-payment sweeper, and the whole admin API
surface (CRUD validation, catalog, outbox feed, requeue, bulk send).
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import auth_header
from app.core.settings_store import settings_store
from app.models.email_automation import EmailAutomation, EmailOutbox
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from app.services.email import dispatcher
from app.services.email.automation import enqueue_for_trigger
from app.services.payment_lifecycle import (
    activate_subscription_for_payment, mark_payment_failed,
)


# ---------------------------------------------------------------- helpers
def _mk_automation(db, *, trigger="user.signup", conditions=None,
                   delay=20, policy="once_per_user", cooldown=0,
                   active=True, name="Signup nudge",
                   attachments=None) -> EmailAutomation:
    a = EmailAutomation(
        tenant_id=1, name=name, trigger_key=trigger,
        conditions=conditions if conditions is not None
        else [{"type": "has_active_subscription", "value": False}],
        delay_minutes=delay, subject="Hi {{name}}",
        html_body="<p>Hello {{name}} — {{plan_name}}{{score}}</p>",
        attachments=attachments or [], send_policy=policy,
        cooldown_days=cooldown, is_active=active,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def _set_master(db, admin, value: bool):
    """Write the switch explicitly. Tests must never rely on the default:
    the module-level fakeredis instance is shared across tests and the
    settings_store read-through cache (30s TTL) leaks a previous test's
    cached value into the next one. An explicit set() invalidates it."""
    settings_store.set("email.lifecycle_enabled", value,
                       db=db, updated_by=admin.id)


def _enable_master(db, admin):
    _set_master(db, admin, True)


def _pending(db, user_id=None):
    q = db.query(EmailOutbox).filter_by(status="pending")
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    return q.all()


@pytest.fixture
def plan(db):
    p = Plan(name="Full Prep", slug="full-prep", description="d",
             bundle_type="exam_bundle", base_price_paise=499900,
             duration_days=180, is_active=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


@pytest.fixture
def payment(db, user, plan):
    p = Payment(user_id=user.id, plan_id=plan.id,
                provider_name="razorpay", provider_order_id="order_t1",
                amount_paise=499900, currency="INR", status="created",
                idempotency_key="idem_t1")
    db.add(p); db.commit(); db.refresh(p)
    return p


# ------------------------------------------------------------ hook: auth
def test_signup_enqueues_with_delay(client, db, admin):
    auto = _mk_automation(db, delay=20)
    before = datetime.now(timezone.utc)
    r = client.post("/api/v1/auth/signup", json={
        "email": "newbie@example.com", "password": "password123",
        "name": "Newbie"})
    assert r.status_code == 201, r.text
    rows = _pending(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.automation_id == auto.id
    assert row.to_email == "newbie@example.com"
    assert row.source == "automation"
    # Scheduled ~20 minutes out (admin-configurable delay, R5/d).
    lo = before + timedelta(minutes=19)
    hi = datetime.now(timezone.utc) + timedelta(minutes=21)
    assert lo <= row.scheduled_at <= hi


def test_signup_once_per_user_never_duplicates(client, db, admin, user):
    _mk_automation(db, trigger="user.login", delay=0,
                   policy="once_per_user")
    for _ in range(3):
        r = client.post("/api/v1/auth/login", json={
            "email": user.email, "password": "password123"})
        assert r.status_code == 200
    assert len(db.query(EmailOutbox).all()) == 1


def test_signup_skipped_for_paid_user_at_enqueue(client, db, user):
    _mk_automation(db, trigger="user.login", delay=0)
    db.add(Subscription(
        user_id=user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    r = client.post("/api/v1/auth/login", json={
        "email": user.email, "password": "password123"})
    assert r.status_code == 200
    assert _pending(db) == []


def test_inactive_automation_never_enqueues(client, db):
    _mk_automation(db, active=False)
    r = client.post("/api/v1/auth/signup", json={
        "email": "quiet@example.com", "password": "password123",
        "name": "Quiet"})
    assert r.status_code == 201
    assert db.query(EmailOutbox).all() == []


# --------------------------------------------------------- hook: payment
def test_payment_success_enqueues_and_cancels_nudge(db, user, payment, plan):
    nudge = _mk_automation(db, trigger="user.signup", delay=20)
    pay_auto = _mk_automation(
        db, trigger="payment.success", conditions=[], delay=0,
        policy="every_event", name="Payment received")
    # Simulate the queued signup nudge (user signed up 5 min ago).
    enqueue_for_trigger(db, "user.signup", user)
    assert len(_pending(db, user.id)) == 1

    activate_subscription_for_payment(db, payment)

    rows = db.query(EmailOutbox).order_by(EmailOutbox.id).all()
    by_auto = {r.automation_id: r for r in rows}
    # Nudge cancelled with a truthful reason (R7)…
    assert by_auto[nudge.id].status == "cancelled"
    assert "paid" in by_auto[nudge.id].skip_reason
    # …payment mail queued with the plan context snapshotted.
    assert by_auto[pay_auto.id].status == "pending"
    assert by_auto[pay_auto.id].context["plan_name"] == plan.name


def test_payment_success_verify_webhook_race_is_deduped(db, user, payment):
    _mk_automation(db, trigger="payment.success", conditions=[],
                   delay=0, policy="every_event", name="Payment received")
    activate_subscription_for_payment(db, payment)   # verify path
    activate_subscription_for_payment(db, payment)   # webhook replay
    assert len(db.query(EmailOutbox).all()) == 1     # dedup ref = pay{id}


def test_payment_failed_enqueues(db, user, payment):
    _mk_automation(db, trigger="payment.failed", conditions=[],
                   delay=30, policy="every_event", name="Pay failed")
    mark_payment_failed(db, payment)
    rows = _pending(db, user.id)
    assert len(rows) == 1
    assert rows[0].context["provider"] == "razorpay"


# ------------------------------------------------------------ hook: exam
def test_exam_submit_enqueues_replace_pending(db, user, sample_exam_set):
    from app.services.exam_service import ExamService
    auto = _mk_automation(db, trigger="exam.submitted", conditions=[],
                          delay=2880, policy="replace_pending",
                          name="Exam follow-up")
    svc = ExamService(db)
    attempt = svc.start_attempt(user, sample_exam_set.slug)
    svc.submit(user, attempt.id)
    rows = _pending(db, user.id)
    assert len(rows) == 1
    first_sched = rows[0].scheduled_at
    assert rows[0].context["exam_title"] == sample_exam_set.name

    # Second attempt REPLACES the pending row (one mail per latest exam).
    attempt2 = svc.start_attempt(user, sample_exam_set.slug)
    svc.submit(user, attempt2.id)
    rows = _pending(db, user.id)
    assert len(rows) == 1
    assert rows[0].automation_id == auto.id
    assert rows[0].scheduled_at >= first_sched


def test_anonymous_exam_submit_enqueues_nothing(db, sample_exam_set):
    from app.services.exam_service import ExamService
    _mk_automation(db, trigger="exam.submitted", conditions=[], delay=10)
    svc = ExamService(db)
    attempt = svc.start_attempt("anon-token-1", sample_exam_set.slug)
    svc.submit("anon-token-1", attempt.id)
    assert db.query(EmailOutbox).all() == []


# -------------------------------------------------------------- dispatcher
def _mk_due_row(db, auto, user, *, minutes_ago=1, source="automation",
                context=None):
    row = EmailOutbox(
        tenant_id=1, automation_id=auto.id, user_id=user.id,
        to_email=user.email,
        dedup_key=f"t:{auto.id}:{user.id}:{minutes_ago}:{source}",
        scheduled_at=datetime.now(timezone.utc)
        - timedelta(minutes=minutes_ago),
        status="pending", source=source, context=context or {},
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


@pytest.fixture
def sent_mails(monkeypatch):
    calls: list[dict] = []
    def fake_send(to, subject, html_body, attachments=None):
        calls.append({"to": to, "subject": subject, "html": html_body,
                      "attachments": attachments or []})
        return True
    monkeypatch.setattr("app.services.email.mailer.send_email", fake_send)
    return calls


def test_dispatch_noops_while_master_switch_off(db, admin, user, sent_mails):
    _set_master(db, admin, False)
    auto = _mk_automation(db, conditions=[], delay=0)
    row = _mk_due_row(db, auto, user)
    assert dispatcher.dispatch_due(db) == 0
    db.refresh(row)
    assert row.status == "pending"          # paused, not purged
    assert sent_mails == []


def test_dispatch_sends_due_row_and_records_dates(db, admin, user,
                                                  sent_mails):
    _enable_master(db, admin)
    auto = _mk_automation(db, conditions=[], delay=0)
    row = _mk_due_row(db, auto, user)
    assert dispatcher.dispatch_due(db) == 1
    db.refresh(row)
    assert row.status == "sent"
    assert row.sent_at is not None          # date visible to admin (R7)
    assert sent_mails[0]["to"] == user.email
    # Personalization actually rendered (R3).
    assert user.name in sent_mails[0]["subject"]


def test_dispatch_not_due_yet_stays_pending(db, admin, user, sent_mails):
    _enable_master(db, admin)
    auto = _mk_automation(db, conditions=[], delay=0)
    row = _mk_due_row(db, auto, user, minutes_ago=-30)  # due in 30 min
    assert dispatcher.dispatch_due(db) == 0
    db.refresh(row)
    assert row.status == "pending" and sent_mails == []


def test_dispatch_skips_when_user_paid_during_wait(db, admin, user,
                                                   sent_mails):
    """The R4/R11 case: unpaid nudge queued, user pays before it fires."""
    _enable_master(db, admin)
    auto = _mk_automation(db)  # condition: has NOT paid
    row = _mk_due_row(db, auto, user)
    db.add(Subscription(
        user_id=user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    dispatcher.dispatch_due(db)
    db.refresh(row)
    assert row.status == "skipped"
    assert "condition not met" in row.skip_reason
    assert sent_mails == []


def test_dispatch_skips_disabled_automation(db, admin, user, sent_mails):
    _enable_master(db, admin)
    auto = _mk_automation(db, conditions=[], delay=0, active=False)
    row = _mk_due_row(db, auto, user)
    dispatcher.dispatch_due(db)
    db.refresh(row)
    assert row.status == "skipped"
    assert "disabled" in row.skip_reason


def test_manual_send_bypasses_toggle_and_conditions(db, admin, user,
                                                    sent_mails):
    _enable_master(db, admin)
    # Disabled + unpaid-only condition; user HAS paid. Manual still sends.
    auto = _mk_automation(db, active=False)
    db.add(Subscription(
        user_id=user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    row = _mk_due_row(db, auto, user, source="manual")
    assert dispatcher.dispatch_due(db) == 1
    db.refresh(row)
    assert row.status == "sent"


def test_dispatch_retries_then_fails(db, admin, user, monkeypatch):
    _enable_master(db, admin)
    monkeypatch.setattr("app.services.email.mailer.send_email",
                        lambda *a, **k: False)
    auto = _mk_automation(db, conditions=[], delay=0)
    row = _mk_due_row(db, auto, user)
    now = datetime.now(timezone.utc)
    for i in range(dispatcher.MAX_ATTEMPTS):
        dispatcher.dispatch_due(
            db, now=now + timedelta(seconds=(dispatcher.TICK_SECONDS + 1) * (i + 1)))
        db.refresh(row)
    assert row.status == "failed"
    assert row.attempts == dispatcher.MAX_ATTEMPTS
    assert row.last_error


def test_every_event_cooldown_suppresses_repeat(db, user):
    auto = _mk_automation(db, trigger="payment.failed", conditions=[],
                          delay=0, policy="every_event", cooldown=1,
                          name="Pay failed")
    # A send within the cooldown window…
    db.add(EmailOutbox(
        tenant_id=1, automation_id=auto.id, user_id=user.id,
        to_email=user.email, dedup_key=f"{auto.id}:{user.id}:old",
        scheduled_at=datetime.now(timezone.utc), status="sent",
        sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
        context={}))
    db.commit()
    # …suppresses the next event's enqueue.
    n = enqueue_for_trigger(db, "payment.failed", user, event_ref="pay77")
    assert n == 0


# ---------------------------------------------------------------- sweeper
def test_abandoned_sweep_enqueues_once(db, admin, user, plan):
    _enable_master(db, admin)
    _mk_automation(db, trigger="payment.abandoned", conditions=[],
                   delay=60, policy="every_event", name="Abandoned")
    stale = Payment(user_id=user.id, plan_id=plan.id,
                    provider_name="razorpay", provider_order_id="order_ab",
                    amount_paise=100000, currency="INR", status="created",
                    idempotency_key="idem_ab")
    db.add(stale); db.commit()
    # Backdate creation beyond the 60-minute threshold.
    db.query(Payment).filter_by(id=stale.id).update({
        "created_at": datetime.now(timezone.utc) - timedelta(hours=3)})
    db.commit()

    assert dispatcher.sweep_abandoned_payments(db) == 1
    rows = _pending(db, user.id)
    assert len(rows) == 1
    assert rows[0].context["plan_name"] == plan.name
    # Re-sweep: dedup ref = payment id → no second nudge.
    assert dispatcher.sweep_abandoned_payments(db) == 0
    assert len(_pending(db, user.id)) == 1


def test_captured_payment_is_not_abandoned(db, admin, user, plan, payment):
    _enable_master(db, admin)
    _mk_automation(db, trigger="payment.abandoned", conditions=[],
                   delay=60, policy="every_event", name="Abandoned")
    payment.status = "captured"
    db.query(Payment).filter_by(id=payment.id).update({
        "created_at": datetime.now(timezone.utc) - timedelta(hours=3),
        "status": "captured"})
    db.commit()
    assert dispatcher.sweep_abandoned_payments(db) == 0


# ---------------------------------------------------------------- admin API
def test_admin_crud_and_toggle(client, db, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/email-automations", headers=h, json={
        "name": "Set2 not Set3 nudge",
        "trigger_key": "exam.submitted",
        "conditions": [
            {"type": "exam_set_submitted", "exam_set_id": 2, "value": True},
            {"type": "exam_set_submitted", "exam_set_id": 3, "value": False},
        ],
        "delay_minutes": 60,
        "subject": "Keep going {{name}}",
        "html_body": "<p>{{exam_title}}</p>",
        "send_policy": "replace_pending",
    })
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["is_active"] is False   # ships disabled by default

    # Per-type enable toggle (R6).
    r = client.patch(f"/api/v1/admin/email-automations/{aid}", headers=h,
                     json={"is_active": True})
    assert r.status_code == 200 and r.json()["is_active"] is True

    r = client.get("/api/v1/admin/email-automations", headers=h)
    assert any(a["id"] == aid for a in r.json())

    # Delete cancels the pending queue for that type.
    u = db.query(User).filter_by(email=admin.email).first()
    db.add(EmailOutbox(tenant_id=1, automation_id=aid, user_id=u.id,
                       to_email=u.email, dedup_key=f"{aid}:{u.id}:once",
                       scheduled_at=datetime.now(timezone.utc),
                       status="pending", context={}))
    db.commit()
    r = client.delete(f"/api/v1/admin/email-automations/{aid}", headers=h)
    assert r.status_code == 204
    left = db.query(EmailOutbox).filter_by(automation_id=None).all()
    assert len(left) == 1 and left[0].status == "cancelled"


def test_admin_rejects_unknown_trigger_and_condition(client, admin):
    h = auth_header(client, admin.email)
    base = {"name": "x", "subject": "s", "html_body": "<p>b</p>"}
    # app.core.exceptions.ValidationError maps to 422 in this codebase.
    r = client.post("/api/v1/admin/email-automations", headers=h,
                    json={**base, "trigger_key": "user.telepathy"})
    assert r.status_code == 422
    r = client.post("/api/v1/admin/email-automations", headers=h,
                    json={**base, "trigger_key": "user.signup",
                          "conditions": [{"type": "phase_of_moon"}]})
    assert r.status_code == 422


def test_admin_rejects_oversize_attachments(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/email-automations", headers=h, json={
        "name": "big", "trigger_key": "user.signup",
        "subject": "s", "html_body": "<p>b</p>",
        "attachments": [{
            "url": "/uploads/1/huge.pdf", "filename": "huge.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 20 * 1024 * 1024,
        }],
    })
    assert r.status_code == 422


def test_catalog_endpoint(client, db, admin):
    _set_master(db, admin, False)
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/email-automations/catalog", headers=h)
    assert r.status_code == 200
    body = r.json()
    keys = {t["key"] for t in body["triggers"]}
    assert {"user.signup", "payment.success", "payment.failed",
            "payment.abandoned", "exam.submitted"} <= keys
    assert "name" in body["shared_placeholders"]
    assert any(c["type"] == "has_active_subscription"
               for c in body["condition_types"])
    assert body["master_switch_on"] is False


def test_outbox_feed_and_requeue(client, db, admin, user):
    h = auth_header(client, admin.email)
    auto = _mk_automation(db, conditions=[], delay=0)
    row = _mk_due_row(db, auto, user)
    row.status = "failed"; row.last_error = "smtp boom"
    db.commit()

    r = client.get("/api/v1/admin/email-automations/outbox?status=failed",
                   headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["user_email"] == user.email
    assert item["automation_name"] == auto.name
    assert item["last_error"] == "smtp boom"

    r = client.post(
        f"/api/v1/admin/email-automations/outbox/{row.id}/requeue",
        headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    # Sent rows can't be requeued (would double-send).
    row2 = _mk_due_row(db, auto, user, minutes_ago=2)
    row2.status = "sent"; db.commit()
    r = client.post(
        f"/api/v1/admin/email-automations/outbox/{row2.id}/requeue",
        headers=h)
    assert r.status_code == 422


def test_bulk_send_personalizes_per_user(client, db, admin, user,
                                         sent_mails):
    """R9 end-to-end: bulk-send queues manual rows, dispatch renders each
    with the recipient's OWN name."""
    _enable_master(db, admin)
    auto = _mk_automation(db, conditions=[], delay=0, active=False)
    other = User(email="bob@example.com", password_hash="x", name="Bob",
                 role=UserRole.USER)
    db.add(other); db.commit(); db.refresh(other)

    h = auth_header(client, admin.email)
    r = client.post(
        f"/api/v1/admin/email-automations/{auto.id}/bulk-send",
        headers=h, json={"user_ids": [user.id, other.id, 999999]})
    assert r.status_code == 200, r.text
    assert r.json()["queued"] == 2
    assert r.json()["skipped"] == [
        {"user_id": 999999, "reason": "user not found"}]

    assert dispatcher.dispatch_due(db) == 2
    subjects = {m["to"]: m["subject"] for m in sent_mails}
    assert subjects[user.email] == f"Hi {user.name}"
    assert subjects[other.email] == "Hi Bob"


def test_payments_admin_listing(client, db, admin, user, plan):
    h = auth_header(client, admin.email)
    for i, status in enumerate(["captured", "failed", "created"]):
        db.add(Payment(user_id=user.id, plan_id=plan.id,
                       provider_name="razorpay",
                       provider_order_id=f"order_l{i}",
                       amount_paise=100, currency="INR", status=status,
                       idempotency_key=f"idem_l{i}"))
    db.commit()
    db.query(Payment).filter_by(status="created").update({
        "created_at": datetime.now(timezone.utc) - timedelta(days=2)})
    db.commit()

    r = client.get("/api/v1/admin/payments?status=failed", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["user_email"] == user.email

    r = client.get("/api/v1/admin/payments?abandoned_hours=24", headers=h)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["status"] == "created"

    r = client.get("/api/v1/admin/payments/summary", headers=h)
    assert r.status_code == 200
    assert r.json()["by_status"]["captured"] == 1
    assert r.json()["abandoned_24h"] == 1

    r = client.get("/api/v1/admin/payments?status=bogus", headers=h)
    assert r.status_code == 422


def test_smtp_test_reports_unconfigured(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/email-automations/smtp-test",
                    headers=h, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "Not configured" in body["error"]
