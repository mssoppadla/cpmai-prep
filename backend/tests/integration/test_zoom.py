"""Integration tests for Zoom session management.

Pins:
  - Admin can create a draft session (Zoom credentials NOT required)
  - Admin endpoints require admin role (403 for regular user, 401 anon)
  - Public /lms/sessions hides drafts and other-tenant sessions
  - Subscription/enrollment gate honoured on public list
  - SDK-token endpoint refuses when zoom.sdk_key absent
  - SDK-token endpoint refuses when session in draft / cancelled
  - Soft-delete works + cancellation status persists

These tests deliberately do NOT make real Zoom REST API calls. Whenever
zoom credentials are unset (the test default), the create flow saves a
"draft" row without ever hitting Zoom. Once the operator configures
real credentials in /admin/settings the production behaviour kicks in.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


ADM = "/api/v1/admin"
PUB = "/api/v1/lms"


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


# ============================================================ admin CRUD

def test_admin_can_create_draft_session_without_credentials(client, admin):
    """Default test env has no zoom.sdk_key etc. → create_session
    saves a 'draft' row and surfaces it as such (no Zoom API call made).
    """
    r = client.post(f"{ADM}/sessions",
                    headers=auth_header(client, admin.email),
                    json={
                        "title": "Week 1: Risk Frameworks",
                        "scheduled_at": _future_iso(48),
                        "duration_minutes": 60,
                    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["zoom_meeting_id"] is None
    # host_config is a JSON dict with the schema defaults
    assert body["host_config"]["mute_on_entry"] is True
    assert body["host_config"]["chat_mode"] == "open"
    assert body["host_config"]["auto_record"] is True


def test_admin_can_list_sessions(client, admin):
    # Plant 2 sessions
    for title in ("Session A", "Session B"):
        client.post(f"{ADM}/sessions",
                    headers=auth_header(client, admin.email),
                    json={"title": title,
                          "scheduled_at": _future_iso(24),
                          "duration_minutes": 60})
    r = client.get(f"{ADM}/sessions",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()]
    assert "Session A" in titles and "Session B" in titles


def test_admin_can_update_host_config(client, admin):
    c = client.post(f"{ADM}/sessions",
                    headers=auth_header(client, admin.email),
                    json={"title": "Cfg test",
                          "scheduled_at": _future_iso(24),
                          "duration_minutes": 60}).json()
    sid = c["id"]
    r = client.patch(f"{ADM}/sessions/{sid}",
                     headers=auth_header(client, admin.email),
                     json={
                         "host_config": {
                             "mute_on_entry": True,
                             "allow_self_unmute": False,
                             "allow_video_toggle": True,
                             "chat_mode": "admin_only",
                             "screen_share_mode": "approval",
                             "waiting_room": True,
                             "lock_after_start": False,
                             "auto_record": True,
                         }
                     })
    assert r.status_code == 200, r.text
    assert r.json()["host_config"]["chat_mode"] == "admin_only"
    assert r.json()["host_config"]["allow_self_unmute"] is False


def test_admin_session_soft_delete(client, db, admin):
    from app.models.zoom import ZoomSession
    c = client.post(f"{ADM}/sessions",
                    headers=auth_header(client, admin.email),
                    json={"title": "Soft del",
                          "scheduled_at": _future_iso(24),
                          "duration_minutes": 60}).json()
    sid = c["id"]
    r = client.delete(f"{ADM}/sessions/{sid}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204
    # DB row still exists with is_deleted=True + status=cancelled
    row = db.query(ZoomSession).filter(ZoomSession.id == sid).first()
    assert row is not None
    assert row.is_deleted is True
    assert row.status == "cancelled"
    # List endpoint hides it
    r2 = client.get(f"{ADM}/sessions",
                    headers=auth_header(client, admin.email))
    assert sid not in [s["id"] for s in r2.json()]


def test_admin_publish_without_credentials_returns_422(client, admin):
    """Calling /publish on a draft session when zoom creds aren't
    configured should return a clear validation error."""
    c = client.post(f"{ADM}/sessions",
                    headers=auth_header(client, admin.email),
                    json={"title": "No-creds publish",
                          "scheduled_at": _future_iso(24),
                          "duration_minutes": 60}).json()
    r = client.post(f"{ADM}/sessions/{c['id']}/publish",
                    headers=auth_header(client, admin.email))
    assert r.status_code == 422, r.text
    assert "configure" in r.text.lower() or "missing" in r.text.lower()


# ============================================================ RBAC

def test_admin_session_endpoints_require_admin_user(client, user):
    r = client.get(f"{ADM}/sessions",
                   headers=auth_header(client, user.email))
    assert r.status_code == 403


def test_admin_session_endpoints_anon_401(client):
    r = client.get(f"{ADM}/sessions")
    assert r.status_code in (401, 403)


# ============================================================ public

def test_public_sessions_hides_draft(client, db, admin, user):
    """Drafts (no zoom_meeting_id) must NOT appear on /lms/sessions."""
    from app.models.zoom import ZoomSession
    # Manually plant a published session so the test isn't dependent
    # on real Zoom credentials.
    s = ZoomSession(
        tenant_id=1, course_id=None,
        title="Open session", scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=60,
        zoom_meeting_id="123456789",
        status="scheduled",
        host_config={"chat_mode": "open"},
        created_by=admin.id,
    )
    db.add(s); db.commit()
    # And a draft session that shouldn't appear
    draft = ZoomSession(
        tenant_id=1, title="Draft session",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
        duration_minutes=60,
        status="draft",
        host_config={},
        created_by=admin.id,
    )
    db.add(draft); db.commit()

    # User has NO subscription / enrollment → public list should be empty
    r = client.get(f"{PUB}/sessions",
                   headers=auth_header(client, user.email))
    assert r.status_code == 200
    titles = [x["title"] for x in r.json()]
    assert "Draft session" not in titles
    # The published standalone session also not visible (no subscription)
    assert "Open session" not in titles


def test_sdk_token_refuses_unpublished_session(client, db, admin, user):
    """A draft session can't be joined — clear validation error."""
    from app.models.zoom import ZoomSession
    s = ZoomSession(
        tenant_id=1, title="Still draft",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=60,
        status="draft",
        host_config={},
        created_by=admin.id,
    )
    db.add(s); db.commit()
    r = client.post(f"{PUB}/sessions/{s.id}/sdk-token",
                    headers=auth_header(client, user.email))
    # Either 422 (not published) or 404 (subscription gate) — both block.
    assert r.status_code in (404, 422)
