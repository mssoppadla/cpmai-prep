"""Feature tests: (1) alternate email linked by browser anon_id; (2) admin can view any user's
exam attempt result; (3) payment-time LinkedIn capture upserts a lead."""
from datetime import datetime, timezone

from app.api.v1.endpoints.payments import _capture_linkedin_lead
from app.models.exam_session import ExamSession
from app.models.journey_event import JourneyEvent
from app.models.lead import Lead, LeadSource
from tests.conftest import auth_header


# ---- Feature 1: dual email via anon_id link -----------------------------------------------
def test_alt_email_linked_by_anon_id(client, db, admin, user):
    anon = "browser-anon-xyz"
    db.add(Lead(email="workmail@company.com", source=LeadSource.LANDING_HERO, anon_id=anon,
                linkedin_id="linkedin.com/in/aspirant"))
    db.add(JourneyEvent(event="page.view", user_id=user.id, anon_id=anon,
                        created_at=datetime.now(timezone.utc)))
    db.commit()
    r = client.get("/api/v1/admin/users", headers=auth_header(client, admin.email),
                   params={"q": user.email})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["id"] == user.id)
    assert "workmail@company.com" in (row["alt_emails"] or [])   # different email surfaced
    assert row["linkedin_id"] == "linkedin.com/in/aspirant"      # also linked via anon_id


# ---- Feature 3: admin views any attempt's result ------------------------------------------
def _submitted(db, user_id, exam_set_id, score, passed):
    now = datetime.now(timezone.utc)
    s = ExamSession(user_id=user_id, exam_set_id=exam_set_id, status="submitted", score=score,
                    passed=passed, time_taken_seconds=600, started_at=now, submitted_at=now,
                    expires_at=now)
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_admin_can_view_any_attempt_result(client, db, admin, user, sample_exam_set):
    s = _submitted(db, user.id, sample_exam_set.id, 80, True)
    r = client.get(f"/api/v1/admin/exams/attempts/{s.id}/result",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == s.id


def test_non_admin_blocked_from_admin_attempt_result(client, db, user, sample_exam_set):
    s = _submitted(db, user.id, sample_exam_set.id, 50, False)
    r = client.get(f"/api/v1/admin/exams/attempts/{s.id}/result",
                   headers=auth_header(client, user.email))
    assert r.status_code in (401, 403)


# ---- Feature 2: payment-time LinkedIn capture ---------------------------------------------
def test_capture_linkedin_lead_upserts(db):
    _capture_linkedin_lead(db, "Payer@Example.com", "linkedin.com/in/payer")
    db.commit()
    lead = db.query(Lead).filter(Lead.email == "payer@example.com").first()
    assert lead is not None and lead.linkedin_id == "linkedin.com/in/payer"
    assert lead.source == LeadSource.PRICING_PAGE
    # does not overwrite an existing linkedin, and never errors
    _capture_linkedin_lead(db, "payer@example.com", "linkedin.com/in/other")
    db.commit()
    assert db.query(Lead).filter(Lead.email == "payer@example.com").first().linkedin_id \
        == "linkedin.com/in/payer"
