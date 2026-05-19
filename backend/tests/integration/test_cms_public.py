"""Integration tests for the public CMS endpoints.

Cover three surfaces:
  * GET /api/v1/cms/nav          — auth-aware visibility filter
  * GET /api/v1/cms/pages/{slug} — published-only with visibility enforcement
  * GET /api/v1/cms/landing      — gated by cms.use_cms_landing setting

The visibility tests below are the most important. They pin that:
  - Drafts NEVER appear in the public surfaces (only is_published=true)
  - Soft-deleted pages NEVER appear
  - 'hidden' visibility is excluded from nav but reachable by direct URL
  - 'authenticated' visibility returns 401 to anon (sign-in prompt)
  - 'subscribed' visibility returns 402 to non-subscribers (paywall)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.settings_store import settings_store
from app.models.content_page import ContentPage
from app.models.subscription import Subscription
from tests.conftest import auth_header


NAV_PATH     = "/api/v1/cms/nav"
PAGE_PATH    = "/api/v1/cms/pages"
LANDING_PATH = "/api/v1/cms/landing"


# ----------------------------------------------------- fixtures

def _mkpage(db, **kw) -> ContentPage:
    base = dict(
        tenant_id=1, slug="page", title="Page",
        blocks=[], nav_visibility="always", nav_order=100,
        is_published=True, is_deleted=False, is_landing=False,
    )
    base.update(kw)
    p = ContentPage(**base)
    db.add(p); db.commit(); db.refresh(p)
    return p


@pytest.fixture
def published_pages(db, default_tenant):
    """Three published pages with different visibility tiers, plus one
    hidden, one draft, and one soft-deleted. Used to exercise the
    visibility filter across most tests."""
    pages = {
        "always":   _mkpage(db, slug="about",   title="About",   nav_visibility="always",        nav_order=10),
        "auth":     _mkpage(db, slug="members", title="Members", nav_visibility="authenticated", nav_order=20),
        "sub":      _mkpage(db, slug="premium", title="Premium", nav_visibility="subscribed",    nav_order=30),
        "hidden":   _mkpage(db, slug="secret",  title="Secret",  nav_visibility="hidden",        nav_order=40),
        "draft":    _mkpage(db, slug="draft",   title="Draft",   nav_visibility="always",        nav_order=50, is_published=False),
        "deleted":  _mkpage(db, slug="rip",     title="Rip",     nav_visibility="always",        nav_order=60, is_deleted=True),
    }
    return pages


@pytest.fixture
def subscribed_user(db, user):
    """User from the base fixture, plus an active subscription so the
    'subscribed' visibility tier passes."""
    s = Subscription(
        user_id=user.id,
        plan_id=None,
        plan="pro",        # legacy NOT NULL label column
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        revoked_at=None,
        source="test",
    )
    db.add(s); db.commit()
    return user


# ----------------------------------------------------- /cms/nav

def test_nav_anon_sees_only_always_visible(client, published_pages):
    r = client.get(NAV_PATH)
    assert r.status_code == 200, r.text
    slugs = [item["slug"] for item in r.json()]
    assert slugs == ["about"]  # everything else is hidden/auth-only/sub/draft/deleted


def test_nav_authenticated_sees_always_plus_authenticated(client, user, published_pages):
    r = client.get(NAV_PATH, headers=auth_header(client, user.email))
    assert r.status_code == 200, r.text
    slugs = sorted(item["slug"] for item in r.json())
    assert slugs == ["about", "members"]  # not premium (no sub), not hidden/draft/deleted


def test_nav_subscribed_sees_all_three_tiers(client, subscribed_user, published_pages):
    r = client.get(NAV_PATH, headers=auth_header(client, subscribed_user.email))
    assert r.status_code == 200, r.text
    slugs = sorted(item["slug"] for item in r.json())
    assert slugs == ["about", "members", "premium"]


def test_nav_excludes_drafts_soft_deleted_and_hidden(client, published_pages):
    """Sanity guard: even if our filter regresses, these three things
    must never appear in nav."""
    r = client.get(NAV_PATH)
    slugs = [item["slug"] for item in r.json()]
    assert "draft" not in slugs
    assert "rip" not in slugs       # soft-deleted
    assert "secret" not in slugs    # hidden


def test_nav_ordered_by_nav_order(client, db, default_tenant):
    _mkpage(db, slug="z-page", title="Z", nav_order=10)
    _mkpage(db, slug="a-page", title="A", nav_order=20)
    _mkpage(db, slug="m-page", title="M", nav_order=15)
    r = client.get(NAV_PATH)
    slugs = [i["slug"] for i in r.json()]
    assert slugs == ["z-page", "m-page", "a-page"]  # by nav_order


def test_nav_reorder_via_patch_updates_public_response(
    client, db, admin, default_tenant,
):
    """End-to-end check of the operator reorder flow:

      1. Three published pages exist in initial nav_order A → B → C.
      2. Admin PATCHes nav_order on B (swap B with A).
      3. GET /cms/nav now returns the new ordering.

    Pins that the admin reorder action (driven from the list page's
    up/down arrows) is actually reflected on the public site without
    any cache or sort weirdness.
    """
    # Three pages, initial order: a (10), b (20), c (30)
    a = _mkpage(db, slug="a", title="A page", nav_order=10)
    b = _mkpage(db, slug="b", title="B page", nav_order=20)
    c = _mkpage(db, slug="c", title="C page", nav_order=30)

    # Sanity: starting order is a, b, c
    r0 = client.get(NAV_PATH)
    assert [item["slug"] for item in r0.json()] == ["a", "b", "c"]

    # Admin reorders: swap A and B by editing nav_order via PATCH on
    # the regular update endpoint (this is exactly what the list
    # page's up/down arrow buttons do — see admin/content-pages page.tsx).
    base_admin = "/api/v1/admin/content-pages"
    headers = auth_header(client, admin.email)
    assert client.patch(f"{base_admin}/{a.id}", headers=headers,
                        json={"nav_order": 20}).status_code == 200
    assert client.patch(f"{base_admin}/{b.id}", headers=headers,
                        json={"nav_order": 10}).status_code == 200

    # After PATCHes, public nav should reflect the swap: b, a, c
    r1 = client.get(NAV_PATH)
    assert r1.status_code == 200, r1.text
    assert [item["slug"] for item in r1.json()] == ["b", "a", "c"]

    # Move C to the front (nav_order=1)
    assert client.patch(f"{base_admin}/{c.id}", headers=headers,
                        json={"nav_order": 1}).status_code == 200
    r2 = client.get(NAV_PATH)
    assert [item["slug"] for item in r2.json()] == ["c", "b", "a"]


def test_nav_order_tie_broken_by_title(client, db, default_tenant):
    """When two pages share nav_order, the public nav sorts the tie by
    title (ascending). Pinned so accidental re-ordering of the SQL
    ORDER BY doesn't silently scramble equal-order pages."""
    _mkpage(db, slug="banana", title="Banana", nav_order=10)
    _mkpage(db, slug="apple",  title="Apple",  nav_order=10)
    _mkpage(db, slug="cherry", title="Cherry", nav_order=10)
    r = client.get(NAV_PATH)
    assert [item["label"] for item in r.json()] == ["Apple", "Banana", "Cherry"]


def test_nav_uses_effective_label(client, db, default_tenant):
    """When nav_label is set, the nav uses that; else falls back to title."""
    _mkpage(db, slug="a", title="Long Page Title", nav_label="Short")
    _mkpage(db, slug="b", title="Plain Title")
    r = client.get(NAV_PATH)
    labels = {i["slug"]: i["label"] for i in r.json()}
    assert labels["a"] == "Short"
    assert labels["b"] == "Plain Title"


# ----------------------------------------------------- /cms/pages/{slug}

def test_page_anon_sees_always_visible(client, published_pages):
    r = client.get(f"{PAGE_PATH}/about")
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "about"
    # Public payload should NOT leak tenant_id (admin-only field)
    assert "tenant_id" not in r.json()


def test_page_anon_blocked_from_authenticated(client, published_pages):
    """Page exists but anon can't see it → 401 (prompts sign-in)."""
    r = client.get(f"{PAGE_PATH}/members")
    assert r.status_code == 401


def test_page_authenticated_can_see_authenticated_pages(client, user, published_pages):
    r = client.get(f"{PAGE_PATH}/members", headers=auth_header(client, user.email))
    assert r.status_code == 200


def test_page_authenticated_blocked_from_subscribed(client, user, published_pages):
    """Signed-in but not subscribed → 402."""
    r = client.get(f"{PAGE_PATH}/premium", headers=auth_header(client, user.email))
    assert r.status_code == 402


def test_page_subscribed_can_see_all_tiers(client, subscribed_user, published_pages):
    for slug in ("about", "members", "premium"):
        r = client.get(f"{PAGE_PATH}/{slug}",
                       headers=auth_header(client, subscribed_user.email))
        assert r.status_code == 200, (slug, r.text)


def test_page_hidden_is_accessible_by_direct_url(client, published_pages):
    """'hidden' visibility means 'not in nav', NOT 'private'. Phase 1
    decision — change this if you ever need private pages."""
    r = client.get(f"{PAGE_PATH}/secret")
    assert r.status_code == 200


def test_page_draft_returns_404(client, published_pages):
    """Drafts are never publicly fetchable."""
    r = client.get(f"{PAGE_PATH}/draft")
    assert r.status_code == 404


def test_page_soft_deleted_returns_404(client, published_pages):
    r = client.get(f"{PAGE_PATH}/rip")
    assert r.status_code == 404


def test_page_missing_returns_404(client, published_pages):
    r = client.get(f"{PAGE_PATH}/nonexistent")
    assert r.status_code == 404


# ----------------------------------------------------- /cms/landing

def test_landing_404_when_setting_disabled(client, db, default_tenant):
    """Default setting = false → landing endpoint always 404, even if
    a page is marked is_landing."""
    _mkpage(db, slug="home", title="Home", is_landing=True)
    r = client.get(LANDING_PATH)
    assert r.status_code == 404


def _enable_cms_landing(db, admin):
    settings_store.set("cms.use_cms_landing", True, db=db, updated_by=admin.id)


def _disable_cms_landing(db, admin):
    settings_store.set("cms.use_cms_landing", False, db=db, updated_by=admin.id)


def test_landing_404_when_setting_enabled_but_no_page_marked(
    client, db, admin, default_tenant,
):
    _enable_cms_landing(db, admin)
    try:
        r = client.get(LANDING_PATH)
        assert r.status_code == 404
    finally:
        _disable_cms_landing(db, admin)


def test_landing_returns_landing_page_when_enabled(
    client, db, admin, default_tenant,
):
    _mkpage(db, slug="home", title="Home", is_landing=True)
    _enable_cms_landing(db, admin)
    try:
        r = client.get(LANDING_PATH)
        assert r.status_code == 200, r.text
        assert r.json()["slug"] == "home"
    finally:
        _disable_cms_landing(db, admin)


def test_landing_ignores_unpublished_and_deleted(
    client, db, admin, default_tenant,
):
    """Even with the setting on, a draft or soft-deleted landing
    page is invisible."""
    _mkpage(db, slug="home", title="Home", is_landing=True, is_published=False)
    _enable_cms_landing(db, admin)
    try:
        r = client.get(LANDING_PATH)
        assert r.status_code == 404
    finally:
        _disable_cms_landing(db, admin)


# ----------------------------------------------------- admin set-landing

SET_LANDING = "/api/v1/admin/content-pages/{id}/set-landing"
CLEAR_LANDING = "/api/v1/admin/content-pages/{id}/clear-landing"


def test_set_landing_marks_page_and_unsets_previous(client, db, admin, default_tenant):
    """Setting page B as landing un-sets page A in the same transaction.
    Without this, the partial unique index would 500 the second call."""
    a = _mkpage(db, slug="a", title="A", is_landing=True)
    b = _mkpage(db, slug="b", title="B")
    r = client.post(SET_LANDING.format(id=b.id),
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["is_landing"] is True
    db.expire_all()
    assert db.get(ContentPage, a.id).is_landing is False
    assert db.get(ContentPage, b.id).is_landing is True


def test_set_landing_audit_logged(client, db, admin, default_tenant):
    p = _mkpage(db, slug="home", title="Home")
    client.post(SET_LANDING.format(id=p.id),
                headers=auth_header(client, admin.email))
    from app.models.audit_log import AuditLog
    from sqlalchemy import desc
    row = (db.query(AuditLog)
            .filter(AuditLog.action == "content_page.set_landing")
            .order_by(desc(AuditLog.id)).first())
    assert row is not None
    assert row.tenant_id == 1
    assert row.metadata_json["id"] == p.id


def test_set_landing_404_for_missing_page(client, db, admin, default_tenant):
    r = client.post(SET_LANDING.format(id=99999),
                    headers=auth_header(client, admin.email))
    assert r.status_code == 404


def test_set_landing_rbac_anonymous_401(client, db, default_tenant):
    p = _mkpage(db, slug="home", title="Home")
    r = client.post(SET_LANDING.format(id=p.id))
    assert r.status_code == 401


def test_set_landing_rbac_user_403(client, db, user, default_tenant):
    p = _mkpage(db, slug="home", title="Home")
    r = client.post(SET_LANDING.format(id=p.id),
                    headers=auth_header(client, user.email))
    assert r.status_code == 403


def test_clear_landing_removes_flag(client, db, admin, default_tenant):
    p = _mkpage(db, slug="home", title="Home", is_landing=True)
    r = client.post(CLEAR_LANDING.format(id=p.id),
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["is_landing"] is False
    db.expire_all()
    assert db.get(ContentPage, p.id).is_landing is False


def test_clear_landing_on_non_landing_page_is_noop(client, db, admin, default_tenant):
    p = _mkpage(db, slug="other", title="Other")
    r = client.post(CLEAR_LANDING.format(id=p.id),
                    headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    assert r.json()["is_landing"] is False
