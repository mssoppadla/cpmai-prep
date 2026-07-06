"""Integration tests: lead.captured trigger + suppression groups.

Contract: docs/contracts/email-automation.md §4a/§4b.

Covers: landing-form submissions enqueue lead-recipient outbox rows,
marketing-consent gating, email-keyed dedup across resubmits, lead
personalization at dispatch, the suppression group first-sent-wins rule
(including across the lead → signed-up-user identity change), honest
Activity recording, and manual-send bypass.
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import auth_header
from app.core.settings_store import settings_store
from app.models.email_automation import EmailAutomation, EmailOutbox
from app.models.lead import Lead, LeadSource
from app.models.user import User, UserRole
from app.services.email import dispatcher
from app.services.email.automation import (
    enqueue_for_lead_trigger, lead_recipient_ns,
)


def _set_master(db, admin, value: bool):
    settings_store.set("email.lifecycle_enabled", value,
                       db=db, updated_by=admin.id)


def _mk_automation(db, *, trigger="lead.captured", conditions=None,
                   delay=0, policy="once_per_user", group=None,
                   active=True, name="Landing kit") -> EmailAutomation:
    a = EmailAutomation(
        tenant_id=1, name=name, trigger_key=trigger,
        conditions=conditions if conditions is not None else [],
        delay_minutes=delay, subject="Hi {{name}} — {{lead_source}}",
        html_body="<p>{{name}} / {{target_exam_date}}</p>",
        attachments=[], send_policy=policy, cooldown_days=0,
        is_active=active, suppression_group=group,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def _submit_form(client, email="visitor@example.com", name="Visitor",
                 consent=True):
    return client.post("/api/v1/leads", json={
        "email": email, "name": name, "source": "landing_hero",
        "consent_marketing": consent,
        "target_exam_date": "2026-09-30",
    })


@pytest.fixture
def sent_mails(monkeypatch):
    calls: list[dict] = []
    def fake_send(to, subject, html_body, attachments=None):
        calls.append({"to": to, "subject": subject, "html": html_body})
        return True
    monkeypatch.setattr("app.services.email.mailer.send_email", fake_send)
    return calls


# ------------------------------------------------------------ lead enqueue
def test_landing_form_enqueues_lead_mail(client, db):
    auto = _mk_automation(db)
    r = _submit_form(client)
    assert r.status_code == 201, r.text
    rows = db.query(EmailOutbox).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.automation_id == auto.id
    assert row.user_id is None                      # lead recipient
    assert row.lead_id is not None
    assert row.to_email == "visitor@example.com"
    assert row.context["lead_source"] == "landing_hero"
    assert row.context["target_exam_date"] == "30 Sep 2026"


def test_resubmitted_form_does_not_requeue_once_per_user(client, db):
    """POST /leads inserts a NEW Lead row each time — dedup must be
    email-keyed so the same person doesn't get the kit mail twice."""
    _mk_automation(db, policy="once_per_user")
    _submit_form(client)
    _submit_form(client)   # same email, new Lead row
    assert db.query(EmailOutbox).count() == 1
    assert db.query(Lead).count() == 2


def test_consent_condition_gates_lead_mail(client, db):
    _mk_automation(db, conditions=[
        {"type": "marketing_consent", "value": True}])
    r = _submit_form(client, consent=False)
    assert r.status_code == 201
    assert db.query(EmailOutbox).count() == 0
    _submit_form(client, email="ok@example.com", consent=True)
    assert db.query(EmailOutbox).count() == 1


def test_lead_dispatch_personalizes_from_lead(client, db, admin,
                                              sent_mails):
    _set_master(db, admin, True)
    _mk_automation(db)
    _submit_form(client, email="pia@example.com", name="Pia")
    assert dispatcher.dispatch_due(db) == 1
    assert sent_mails[0]["to"] == "pia@example.com"
    assert sent_mails[0]["subject"] == "Hi Pia — landing_hero"
    row = db.query(EmailOutbox).one()
    assert row.status == "sent" and row.sent_at is not None


def test_lead_ns_is_stable_and_case_insensitive():
    assert lead_recipient_ns("A@B.com") == lead_recipient_ns(" a@b.com ")
    assert lead_recipient_ns("a@b.com") != lead_recipient_ns("c@d.com")


# ------------------------------------------------------- suppression group
def test_suppression_lead_mail_silences_signup_welcome(client, db, admin,
                                                       sent_mails):
    """The user's scenario: landing-form kit mail (with attachment) went
    out → the signup welcome in the same group must NOT send when the
    same person creates an account — recorded in Activity with the
    suppressing mail type's name."""
    _set_master(db, admin, True)
    kit = _mk_automation(db, group="welcome-kit", name="Landing kit")
    welcome = _mk_automation(
        db, trigger="user.signup", group="welcome-kit",
        conditions=[{"type": "has_active_subscription", "value": False}],
        delay=0, name="Signup welcome")

    _submit_form(client, email="grace@example.com", name="Grace")
    assert dispatcher.dispatch_due(db) == 1          # kit mail sent

    r = client.post("/api/v1/auth/signup", json={
        "email": "grace@example.com", "password": "password123",
        "name": "Grace"})
    assert r.status_code == 201
    assert dispatcher.dispatch_due(db) == 0          # welcome suppressed

    rows = {row.automation_id: row for row in db.query(EmailOutbox).all()}
    assert rows[kit.id].status == "sent"
    assert rows[welcome.id].status == "skipped"
    assert "suppressed" in rows[welcome.id].skip_reason
    assert "Landing kit" in rows[welcome.id].skip_reason
    assert len(sent_mails) == 1                      # exactly ONE mail


def test_suppression_is_first_sent_wins_not_first_queued(db, admin, user,
                                                         sent_mails):
    """A pending (unsent) row in the group does NOT suppress — only a
    SENT one. Two automations, both pending: earlier-scheduled sends,
    the other is then suppressed in the same tick."""
    _set_master(db, admin, True)
    a1 = _mk_automation(db, trigger="user.login", group="g1", name="First")
    a2 = _mk_automation(db, trigger="user.login", group="g1", name="Second")
    now = datetime.now(timezone.utc)
    for auto, mins_ago in ((a1, 10), (a2, 5)):
        db.add(EmailOutbox(
            tenant_id=1, automation_id=auto.id, user_id=user.id,
            to_email=user.email, dedup_key=f"{auto.id}:{user.id}:once",
            scheduled_at=now - timedelta(minutes=mins_ago),
            status="pending", source="automation", context={}))
    db.commit()
    assert dispatcher.dispatch_due(db) == 1
    rows = {r.automation_id: r for r in db.query(EmailOutbox).all()}
    assert rows[a1.id].status == "sent"
    assert rows[a2.id].status == "skipped"
    assert "First" in rows[a2.id].skip_reason


def test_no_group_means_no_suppression(db, admin, user, sent_mails):
    _set_master(db, admin, True)
    a1 = _mk_automation(db, trigger="user.login", group=None, name="A")
    a2 = _mk_automation(db, trigger="user.login", group=None, name="B")
    now = datetime.now(timezone.utc)
    for auto in (a1, a2):
        db.add(EmailOutbox(
            tenant_id=1, automation_id=auto.id, user_id=user.id,
            to_email=user.email, dedup_key=f"{auto.id}:{user.id}:once",
            scheduled_at=now - timedelta(minutes=1),
            status="pending", source="automation", context={}))
    db.commit()
    assert dispatcher.dispatch_due(db) == 2


def test_manual_send_bypasses_suppression(db, admin, user, sent_mails):
    _set_master(db, admin, True)
    a1 = _mk_automation(db, trigger="user.login", group="g2", name="A")
    a2 = _mk_automation(db, trigger="user.login", group="g2", name="B")
    now = datetime.now(timezone.utc)
    db.add(EmailOutbox(   # group-mate already SENT
        tenant_id=1, automation_id=a1.id, user_id=user.id,
        to_email=user.email, dedup_key=f"{a1.id}:{user.id}:once",
        scheduled_at=now, status="sent", sent_at=now,
        source="automation", context={}))
    db.add(EmailOutbox(   # manual send of the other group member
        tenant_id=1, automation_id=a2.id, user_id=user.id,
        to_email=user.email, dedup_key=f"manual:{a2.id}:{user.id}:x",
        scheduled_at=now - timedelta(minutes=1),
        status="pending", source="manual", context={}))
    db.commit()
    assert dispatcher.dispatch_due(db) == 1   # manual goes out anyway


# ----------------------------------------------------- lead conditions
def test_lead_conditions_resolve_matching_user(client, db, user):
    """A lead whose email belongs to a PAID account must not match the
    'has NOT paid' condition."""
    from app.models.subscription import Subscription
    _mk_automation(db, conditions=[
        {"type": "has_active_subscription", "value": False}])
    db.add(Subscription(
        user_id=user.id, plan="pro", status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    _submit_form(client, email=user.email)   # lead with the user's email
    assert db.query(EmailOutbox).count() == 0


def test_lead_without_account_counts_as_unpaid(client, db):
    _mk_automation(db, conditions=[
        {"type": "has_active_subscription", "value": False}])
    _submit_form(client, email="stranger@example.com")
    assert db.query(EmailOutbox).count() == 1


# --------------------------------------------------------------- admin API
def test_admin_persists_suppression_group_and_catalog(client, db, admin):
    _set_master(db, admin, False)
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/email-automations", headers=h, json={
        "name": "Kit", "trigger_key": "lead.captured",
        "conditions": [{"type": "marketing_consent", "value": True}],
        "subject": "s", "html_body": "<p>b</p>",
        "suppression_group": "  welcome-kit  ",
    })
    assert r.status_code == 201, r.text
    assert r.json()["suppression_group"] == "welcome-kit"   # trimmed

    # Blank clears it.
    aid = r.json()["id"]
    r = client.patch(f"/api/v1/admin/email-automations/{aid}", headers=h,
                     json={"suppression_group": "   "})
    assert r.json()["suppression_group"] is None

    r = client.get("/api/v1/admin/email-automations/catalog", headers=h)
    body = r.json()
    assert any(t["key"] == "lead.captured" for t in body["triggers"])
    assert any(c["type"] == "marketing_consent"
               for c in body["condition_types"])


def test_outbox_feed_shows_lead_rows(client, db, admin):
    h = auth_header(client, admin.email)
    auto = _mk_automation(db)
    lead = Lead(email="feed-lead@example.com", name="Feed Lead",
                source=LeadSource.LANDING_HERO, consent_marketing=True)
    db.add(lead); db.commit(); db.refresh(lead)
    enqueue_for_lead_trigger(db, "lead.captured", lead)

    r = client.get(
        "/api/v1/admin/email-automations/outbox?user_email=feed-lead",
        headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["lead_id"] == lead.id
    assert item["user_id"] is None
    assert item["user_email"] == "feed-lead@example.com"
    assert item["automation_name"] == auto.name
