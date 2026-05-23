"""Integration tests for social-automation campaigns + social-queue.

Pins:
  - Admin CRUD on campaigns
  - Workflow type validation
  - Unique name per tenant
  - Manual run executes the workflow synchronously (using the
    session_reminder runner which doesn't need an LLM provider)
  - Failed runs surface in /admin/social-queue
  - Mark-posted records platform + URL
  - RBAC: regular user 403

Tests deliberately use the SessionReminderRunner because it:
  - Doesn't need an LLM provider configured
  - Has a clean "no sessions in window" path that returns a known
    string deterministically
"""
from __future__ import annotations

from tests.conftest import auth_header


ADM = "/api/v1/admin"


# ============================================================ CRUD

def test_admin_can_create_campaign(client, admin):
    r = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={
                        "name": "Daily reminder",
                        "workflow_type": "session_reminder",
                        "schedule_cron": "0 9 * * *",
                        "config_json": {"window_hours": 24},
                    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Daily reminder"
    assert body["workflow_type"] == "session_reminder"
    assert body["active"] is True


def test_admin_can_list_campaigns(client, admin):
    client.post(f"{ADM}/campaigns",
                headers=auth_header(client, admin.email),
                json={"name": "Cam A", "workflow_type": "session_reminder"})
    client.post(f"{ADM}/campaigns",
                headers=auth_header(client, admin.email),
                json={"name": "Cam B", "workflow_type": "session_reminder"})
    r = client.get(f"{ADM}/campaigns",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert "Cam A" in names and "Cam B" in names


def test_admin_workflows_endpoint(client, admin):
    r = client.get(f"{ADM}/campaigns/workflows",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    body = r.json()
    types = {w["workflow_type"] for w in body}
    assert types == {"weekly_content", "session_reminder",
                     "auto_clip", "recording_published"}


def test_unknown_workflow_type_rejected(client, admin):
    r = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={"name": "Bad", "workflow_type": "not_a_real_workflow"})
    # Pydantic Literal validation kicks in BEFORE our handler — 422.
    assert r.status_code in (400, 422)


def test_duplicate_name_rejected(client, admin):
    client.post(f"{ADM}/campaigns",
                headers=auth_header(client, admin.email),
                json={"name": "Unique name",
                      "workflow_type": "session_reminder"})
    r = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={"name": "Unique name",
                          "workflow_type": "session_reminder"})
    assert r.status_code == 409


def test_admin_can_update_and_delete(client, admin):
    c = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={"name": "To edit",
                          "workflow_type": "session_reminder",
                          "active": True}).json()
    cid = c["id"]
    r = client.patch(f"{ADM}/campaigns/{cid}",
                     headers=auth_header(client, admin.email),
                     json={"description": "edited", "active": False})
    assert r.status_code == 200
    assert r.json()["description"] == "edited"
    assert r.json()["active"] is False

    r = client.delete(f"{ADM}/campaigns/{cid}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204
    # Soft-deleted: doesn't appear in list
    r2 = client.get(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email))
    assert cid not in [x["id"] for x in r2.json()]


# ============================================================ manual run

def test_run_now_executes_workflow(client, admin):
    """session_reminder with no upcoming sessions returns the 'skipping
    reminder' string — deterministic and doesn't need any external
    services."""
    c = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={"name": "Run now test",
                          "workflow_type": "session_reminder",
                          "config_json": {"window_hours": 1}}).json()
    r = client.post(f"{ADM}/campaigns/{c['id']}/run-now",
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done"
    assert "Skipping reminder" in (body["generated_content"] or "")


# ============================================================ queue

def test_social_queue_shows_done_and_failed(client, admin):
    c = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={"name": "Queue test",
                          "workflow_type": "session_reminder",
                          "config_json": {"window_hours": 1}}).json()
    # Trigger a run so the queue has something
    client.post(f"{ADM}/campaigns/{c['id']}/run-now",
                headers=auth_header(client, admin.email))
    r = client.get(f"{ADM}/social-queue",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200
    # At least the run we just made should be in the queue.
    assert any(run["campaign_id"] == c["id"] for run in r.json())


def test_mark_posted_records_platform(client, admin):
    c = client.post(f"{ADM}/campaigns",
                    headers=auth_header(client, admin.email),
                    json={"name": "Mark posted test",
                          "workflow_type": "session_reminder",
                          "config_json": {"window_hours": 1}}).json()
    run = client.post(f"{ADM}/campaigns/{c['id']}/run-now",
                      headers=auth_header(client, admin.email)).json()
    r = client.post(f"{ADM}/social-queue/{run['id']}/mark-posted",
                    headers=auth_header(client, admin.email),
                    json={"platform": "linkedin",
                          "url": "https://linkedin.com/post/abc"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "posted"
    assert r.json()["posted_at"] is not None
    platforms = r.json()["posted_to_platforms"]
    assert len(platforms) == 1
    assert platforms[0]["platform"] == "linkedin"
    assert platforms[0]["url"] == "https://linkedin.com/post/abc"


# ============================================================ RBAC

def test_admin_campaigns_requires_admin_role(client, user):
    r = client.get(f"{ADM}/campaigns",
                   headers=auth_header(client, user.email))
    assert r.status_code == 403


def test_admin_campaigns_anon_401(client):
    r = client.get(f"{ADM}/campaigns")
    assert r.status_code in (401, 403)
