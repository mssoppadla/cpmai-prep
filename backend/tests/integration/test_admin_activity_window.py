"""Activity-window filter on the admin Users + Contacts feeds: show who LOGGED IN or PERFORMED
an activity (journey_event) within a datetime range."""
from datetime import datetime, timedelta, timezone

from app.models.journey_event import JourneyEvent
from tests.conftest import auth_header


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_users_in_window_by_login(client, db, admin, user):
    now = datetime.now(timezone.utc)
    user.last_login_at = now - timedelta(hours=2)          # logged in during the window
    db.commit()
    r = client.get("/api/v1/admin/users", headers=auth_header(client, admin.email),
                   params={"active_from": _iso(now - timedelta(days=1)), "active_to": _iso(now)})
    assert r.status_code == 200, r.text
    assert user.id in [u["id"] for u in r.json()]


def test_users_in_window_by_activity(client, db, admin, user):
    now = datetime.now(timezone.utc)
    user.last_login_at = now - timedelta(days=100)         # NO recent login…
    db.add(JourneyEvent(event="page.view", user_id=user.id,
                        created_at=now - timedelta(hours=3)))  # …but an activity in the window
    db.commit()
    r = client.get("/api/v1/admin/users", headers=auth_header(client, admin.email),
                   params={"active_from": _iso(now - timedelta(days=1))})
    assert user.id in [u["id"] for u in r.json()]          # matched by activity


def test_users_outside_window_excluded(client, db, admin, user):
    now = datetime.now(timezone.utc)
    user.last_login_at = now - timedelta(days=100)         # old login, no recent activity
    db.commit()
    r = client.get("/api/v1/admin/users", headers=auth_header(client, admin.email),
                   params={"active_from": _iso(now - timedelta(days=1))})
    assert user.id not in [u["id"] for u in r.json()]


def test_contacts_window_filters_leads_by_created(client, db, admin):
    from app.models.lead import Lead, LeadSource
    now = datetime.now(timezone.utc)
    fresh = Lead(email="fresh@example.com", name="Fresh", source=LeadSource.LANDING_HERO,
                 created_at=now - timedelta(hours=1))
    stale = Lead(email="stale@example.com", name="Stale", source=LeadSource.LANDING_HERO,
                 created_at=now - timedelta(days=90))
    db.add_all([fresh, stale]); db.commit()
    r = client.get("/api/v1/admin/leads/contacts", headers=auth_header(client, admin.email),
                   params={"kind": "lead", "active_from": _iso(now - timedelta(days=1)),
                           "active_to": _iso(now)})
    assert r.status_code == 200, r.text
    emails = [c["email"] for c in r.json()]
    assert "fresh@example.com" in emails
    assert "stale@example.com" not in emails
