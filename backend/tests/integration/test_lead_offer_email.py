"""Gating for the lead → auto-offer reply trigger in submit_lead.

The actual SMTP send is exercised in tests/unit/test_email_mailer.py. Here
we assert ONLY the decision to enqueue the background task: consent given,
automation switched on, and no recent send to the same address.

We patch ``app.services.email.send_lead_offer_email`` (the symbol the
endpoint imports at call time) with a recorder, so the FastAPI
BackgroundTask records the lead id instead of opening SMTP.
"""
import pytest

from app.core.settings_store import settings_store
from app.models.audit_log import AuditLog


@pytest.fixture
def recorder(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr("app.services.email.send_lead_offer_email",
                        lambda lead_id: calls.append(lead_id))
    return calls


def _enable(db, admin):
    settings_store.set("email.automation_enabled", True,
                       db=db, updated_by=admin.id)


def _submit(client, email="new@example.com", consent=True):
    return client.post("/api/v1/leads", json={
        "email": email, "name": "New Lead",
        "source": "landing_hero", "consent_marketing": consent,
    })


def test_enqueues_when_consented_and_enabled(client, db, admin, recorder):
    _enable(db, admin)
    r = _submit(client, consent=True)
    assert r.status_code == 201, r.text
    assert recorder == [r.json()["id"]]


def test_skips_without_consent(client, db, admin, recorder):
    _enable(db, admin)
    r = _submit(client, consent=False)
    assert r.status_code == 201
    assert recorder == []


def test_skips_when_automation_disabled(client, db, admin, recorder):
    # Default seed/state: email.automation_enabled is false.
    r = _submit(client, consent=True)
    assert r.status_code == 201
    assert recorder == []


def test_skips_when_recently_emailed(client, db, admin, recorder):
    _enable(db, admin)
    db.add(AuditLog(user_id=None, tenant_id=1,
                    action="lead.offer_email_sent",
                    metadata_json={"email": "repeat@example.com"}))
    db.commit()
    r = _submit(client, email="repeat@example.com", consent=True)
    assert r.status_code == 201
    assert recorder == []
