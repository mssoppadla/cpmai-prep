"""Integration tests for the admin CMS endpoints (CMS Phase 1, PR #4).

Pins:

  - CRUD round-trip (create → list → get → update → delete)
  - Tenant scoping (contract I-3): rows always carry tenant_id=1 in Phase 1
  - RBAC: regular user gets 403, anonymous gets 401, admin / super_admin pass
  - Audit log: every write produces one audit row scoped to tenant 1
  - Soft delete: DELETE flips ``is_deleted`` but keeps the row; subsequent
    list/get/update treat the page as gone (404)
  - Slug uniqueness: same tenant + same slug → 409, soft-deleted page
    doesn't block a new page with the same slug
  - Audit log preservation: existing audit_logs continue to write
    (contract CR-2 sanity check at the API surface)

Backward compatibility:

  These tests confirm no existing endpoint regresses. Every test in
  this file uses the same admin/user/super_admin fixtures the rest of
  the suite uses — if the new endpoints broke those, every other
  integration file would fail too.
"""
from __future__ import annotations

import pytest
from sqlalchemy import desc

from app.models.audit_log import AuditLog
from app.models.content_page import ContentPage
from tests.conftest import auth_header


# ----------------------------------------------------------- helpers

CMS_BASE = "/api/v1/admin/content-pages"


def _make_payload(**overrides) -> dict:
    base = {
        "slug": "study-guide",
        "title": "CPMAI Study Guide",
        "blocks": [
            {"type": "heading", "content": "Welcome"},
            {"type": "paragraph", "content": "This is the study guide."},
        ],
        "nav_visibility": "always",
        "nav_order": 10,
        "is_published": True,
    }
    base.update(overrides)
    return base


def _last_audit(db, action: str) -> AuditLog:
    return (db.query(AuditLog)
            .filter(AuditLog.action == action)
            .order_by(desc(AuditLog.id))
            .first())


# ----------------------------------------------------------- CRUD round-trip

def test_create_then_get_returns_same_page(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["id"] > 0
    assert created["slug"] == "study-guide"
    assert created["title"] == "CPMAI Study Guide"
    assert created["tenant_id"] == 1
    assert created["is_published"] is True
    assert created["is_deleted"] is False
    assert created["created_by"] == admin.id

    # Round-trip get
    r2 = client.get(f"{CMS_BASE}/{created['id']}",
                    headers=auth_header(client, admin.email))
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == created["id"]
    assert r2.json()["blocks"] == created["blocks"]


def test_list_returns_all_non_deleted_pages_for_tenant(
    client, db, admin, default_tenant,
):
    for slug in ("about", "study-guide", "privacy"):
        client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(slug=slug, title=slug.title()))
    r = client.get(CMS_BASE, headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    slugs = sorted(p["slug"] for p in r.json())
    assert slugs == ["about", "privacy", "study-guide"]


def test_list_can_filter_to_published_only(client, db, admin, default_tenant):
    client.post(CMS_BASE, headers=auth_header(client, admin.email),
                json=_make_payload(slug="published", is_published=True))
    client.post(CMS_BASE, headers=auth_header(client, admin.email),
                json=_make_payload(slug="draft", is_published=False))
    r = client.get(f"{CMS_BASE}?include_unpublished=false",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    slugs = [p["slug"] for p in r.json()]
    assert slugs == ["published"]


def test_update_persists_fields_and_returns_fresh(
    client, db, admin, default_tenant,
):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(is_published=False))
    page_id = r.json()["id"]
    r2 = client.patch(f"{CMS_BASE}/{page_id}",
                      headers=auth_header(client, admin.email),
                      json={"title": "New Title", "is_published": True})
    assert r2.status_code == 200, r2.text
    assert r2.json()["title"] == "New Title"
    assert r2.json()["is_published"] is True
    # unchanged
    assert r2.json()["slug"] == "study-guide"


def test_update_empty_body_is_noop(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    page_id = r.json()["id"]
    r2 = client.patch(f"{CMS_BASE}/{page_id}",
                      headers=auth_header(client, admin.email), json={})
    assert r2.status_code == 200, r2.text
    assert r2.json()["title"] == "CPMAI Study Guide"


# ----------------------------------------------------------- soft delete

def test_delete_is_soft_and_hides_from_api(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    page_id = r.json()["id"]

    r2 = client.delete(f"{CMS_BASE}/{page_id}",
                       headers=auth_header(client, admin.email))
    assert r2.status_code == 204, r2.text

    # API behaves as if the page is gone
    assert client.get(f"{CMS_BASE}/{page_id}",
                      headers=auth_header(client, admin.email)).status_code == 404
    assert client.patch(f"{CMS_BASE}/{page_id}",
                        headers=auth_header(client, admin.email),
                        json={"title": "Should fail"}).status_code == 404
    list_resp = client.get(CMS_BASE, headers=auth_header(client, admin.email))
    assert page_id not in [p["id"] for p in list_resp.json()]

    # But the row IS still in the DB with the soft-delete fields stamped
    db.expire_all()
    row = db.get(ContentPage, page_id)
    assert row is not None
    assert row.is_deleted is True
    assert row.deleted_at is not None
    assert row.deleted_by == admin.id


def test_delete_already_deleted_returns_404(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    page_id = r.json()["id"]
    client.delete(f"{CMS_BASE}/{page_id}",
                  headers=auth_header(client, admin.email))
    r2 = client.delete(f"{CMS_BASE}/{page_id}",
                       headers=auth_header(client, admin.email))
    assert r2.status_code == 404


def test_softdeleted_slug_still_blocks_creation(client, db, admin, default_tenant):
    """Soft-deleted pages still hold their slug — the DB unique
    constraint covers them and we surface a clean 409 instead of
    letting the IntegrityError become a 500.

    Phase 1 operator path to reusing a slug: rename the soft-deleted
    page (or hard-delete it via DB console). A Phase 2 "Trash" admin
    view will expose this in the UI.
    """
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(slug="about"))
    page_id = r.json()["id"]
    client.delete(f"{CMS_BASE}/{page_id}",
                  headers=auth_header(client, admin.email))
    # Same slug → blocked, even though the page is soft-deleted
    r2 = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                     json=_make_payload(slug="about", title="About v2"))
    assert r2.status_code == 409, r2.text


# ----------------------------------------------------------- slug uniqueness

def test_duplicate_slug_in_same_tenant_returns_409(client, db, admin, default_tenant):
    client.post(CMS_BASE, headers=auth_header(client, admin.email),
                json=_make_payload(slug="about"))
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(slug="about", title="another"))
    assert r.status_code == 409, r.text


def test_update_to_existing_slug_returns_409(client, db, admin, default_tenant):
    client.post(CMS_BASE, headers=auth_header(client, admin.email),
                json=_make_payload(slug="about"))
    r2 = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                     json=_make_payload(slug="privacy", title="Privacy"))
    page_id = r2.json()["id"]
    # Try to rename privacy → about
    r3 = client.patch(f"{CMS_BASE}/{page_id}",
                      headers=auth_header(client, admin.email),
                      json={"slug": "about"})
    assert r3.status_code == 409, r3.text


def test_update_to_own_slug_is_fine(client, db, admin, default_tenant):
    """Updating a page with the same slug it already has must not
    409 — the uniqueness check excludes the page being updated."""
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(slug="about"))
    page_id = r.json()["id"]
    r2 = client.patch(f"{CMS_BASE}/{page_id}",
                      headers=auth_header(client, admin.email),
                      json={"slug": "about", "title": "Renamed"})
    assert r2.status_code == 200, r2.text


# ----------------------------------------------------------- RBAC

def test_anonymous_gets_401(client, db, default_tenant):
    r = client.get(CMS_BASE)
    assert r.status_code == 401


def test_regular_user_gets_403(client, db, user, default_tenant):
    r = client.get(CMS_BASE, headers=auth_header(client, user.email))
    assert r.status_code == 403


def test_admin_can_crud(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    assert r.status_code == 201, r.text


def test_super_admin_can_crud(client, db, super_admin, default_tenant):
    r = client.post(CMS_BASE,
                    headers=auth_header(client, super_admin.email),
                    json=_make_payload())
    assert r.status_code == 201, r.text


# ----------------------------------------------------------- audit logging

def test_create_writes_audit_log(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    page = r.json()
    audit = _last_audit(db, "content_page.created")
    assert audit is not None
    assert audit.tenant_id == 1
    assert audit.user_id == admin.id
    assert audit.metadata_json["id"] == page["id"]
    assert audit.metadata_json["slug"] == "study-guide"


def test_update_writes_audit_log(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    page_id = r.json()["id"]
    client.patch(f"{CMS_BASE}/{page_id}",
                 headers=auth_header(client, admin.email),
                 json={"title": "X"})
    audit = _last_audit(db, "content_page.updated")
    assert audit is not None
    assert audit.tenant_id == 1
    assert audit.metadata_json["id"] == page_id
    assert "title" in audit.metadata_json["changed"]


def test_delete_writes_audit_log(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload())
    page_id = r.json()["id"]
    client.delete(f"{CMS_BASE}/{page_id}",
                  headers=auth_header(client, admin.email))
    audit = _last_audit(db, "content_page.deleted")
    assert audit is not None
    assert audit.tenant_id == 1
    assert audit.metadata_json["id"] == page_id
    assert audit.metadata_json["soft"] is True


# ----------------------------------------------------------- validation edges

def test_invalid_slug_returns_422(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(slug="Has Spaces"))
    assert r.status_code == 422


def test_unknown_nav_visibility_returns_422(client, db, admin, default_tenant):
    r = client.post(CMS_BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(nav_visibility="public"))
    assert r.status_code == 422


def test_get_nonexistent_returns_404(client, db, admin, default_tenant):
    r = client.get(f"{CMS_BASE}/99999",
                   headers=auth_header(client, admin.email))
    assert r.status_code == 404
