"""Reindex hooks for the site-wide assistant corpora.

Same wiring guard pattern as test_assistant_rag_day1: monkeypatch
``reindex_quietly`` at each ENDPOINT module's import site and assert
the admin CRUD paths fire it with the right (source_type, source_id).
Without these, an admin edits a course / CMS page / live session and
the assistant keeps answering from stale chunks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import auth_header


def _capture(monkeypatch) -> list:
    calls: list = []

    def fake(db, source_type, source_id):
        calls.append((source_type, str(source_id)))

    monkeypatch.setattr(
        "app.api.v1.endpoints.admin.lms.reindex_quietly", fake)
    monkeypatch.setattr(
        "app.api.v1.endpoints.admin.content_pages.reindex_quietly", fake)
    monkeypatch.setattr(
        "app.api.v1.endpoints.admin.zoom.reindex_quietly", fake)
    return calls


def test_course_crud_fires_course_reindex(client, admin, monkeypatch):
    calls = _capture(monkeypatch)
    h = auth_header(client, admin.email)

    r = client.post("/api/v1/admin/courses", headers=h, json={
        "slug": "hook-course", "title": "Hook Course"})
    assert r.status_code == 201, r.text
    cid = str(r.json()["id"])
    assert ("course", cid) in calls

    calls.clear()
    r = client.patch(f"/api/v1/admin/courses/{cid}", headers=h,
                     json={"is_published": True})
    assert r.status_code == 200
    assert ("course", cid) in calls

    calls.clear()
    assert client.delete(f"/api/v1/admin/courses/{cid}",
                         headers=h).status_code == 204
    assert ("course", cid) in calls


def test_content_page_crud_fires_reindex(client, admin, monkeypatch):
    calls = _capture(monkeypatch)
    h = auth_header(client, admin.email)

    r = client.post("/api/v1/admin/content-pages", headers=h, json={
        "slug": "hook-page", "title": "Hook Page",
        "blocks": [{"type": "paragraph",
                     "content": [{"type": "text", "text": "hello"}]}],
        "is_published": True})
    assert r.status_code == 201, r.text
    pid = str(r.json()["id"])
    assert ("content_page", pid) in calls

    calls.clear()
    r = client.patch(f"/api/v1/admin/content-pages/{pid}", headers=h,
                     json={"title": "Renamed"})
    assert r.status_code == 200
    assert ("content_page", pid) in calls

    calls.clear()
    assert client.delete(f"/api/v1/admin/content-pages/{pid}",
                         headers=h).status_code == 204
    assert ("content_page", pid) in calls


def test_zoom_session_crud_fires_reindex(client, admin, monkeypatch):
    calls = _capture(monkeypatch)
    h = auth_header(client, admin.email)

    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    r = client.post("/api/v1/admin/sessions", headers=h, json={
        "title": "Hook Session", "scheduled_at": when,
        "duration_minutes": 60})
    assert r.status_code == 201, r.text
    sid = str(r.json()["id"])
    assert ("zoom_session", sid) in calls

    calls.clear()
    r = client.patch(f"/api/v1/admin/sessions/{sid}", headers=h,
                     json={"title": "Hook Session v2"})
    assert r.status_code == 200
    assert ("zoom_session", sid) in calls

    calls.clear()
    assert client.delete(f"/api/v1/admin/sessions/{sid}",
                         headers=h).status_code == 204
    assert ("zoom_session", sid) in calls
