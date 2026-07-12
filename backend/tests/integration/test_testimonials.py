"""Integration tests for testimonials (landing-page carousel).

Pins:

  - Admin CRUD round-trip (create → list → update → delete)
  - RBAC: regular user 403, anonymous 401, admin passes
  - Audit log: every write produces an audit row
  - Public /content/testimonials: only active rows, ordered by
    display_order then id, and only public fields
  - Landing copy exposes the live-banner + testimonial-section knobs
    with safe defaults
"""
from __future__ import annotations

from sqlalchemy import desc

from app.models.audit_log import AuditLog
from tests.conftest import auth_header

BASE = "/api/v1/admin/testimonials"
PUBLIC = "/api/v1/content/testimonials"


def _make_payload(**overrides) -> dict:
    base = {
        "name": "Sarah T.",
        "role": "AI Project Manager",
        "quote": "Passing the CPMAI on my first try — the mock exams "
                 "and coaching were spot on.",
        "photo_url": "/uploads/1/2026/07/abc-sarah.jpg",
        "link_url": "https://www.linkedin.com/in/sarah-t-example",
        "display_order": 10,
        "is_active": True,
    }
    base.update(overrides)
    return base


def _last_audit(db, action: str) -> AuditLog:
    return (db.query(AuditLog)
            .filter(AuditLog.action == action)
            .order_by(desc(AuditLog.id))
            .first())


# ----------------------------------------------------------- CRUD round-trip

def test_create_list_update_delete_round_trip(client, db, admin):
    headers = auth_header(client, admin.email)

    r = client.post(BASE, headers=headers, json=_make_payload())
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["id"] > 0
    assert created["name"] == "Sarah T."
    assert created["role"] == "AI Project Manager"
    assert created["photo_url"] == "/uploads/1/2026/07/abc-sarah.jpg"
    assert created["link_url"].startswith("https://www.linkedin.com/")
    assert created["is_active"] is True
    assert _last_audit(db, "testimonial.created") is not None

    r2 = client.get(BASE, headers=headers)
    assert r2.status_code == 200
    assert any(row["id"] == created["id"] for row in r2.json())

    r3 = client.patch(f"{BASE}/{created['id']}", headers=headers,
                      json=_make_payload(name="Sarah Taylor",
                                         is_active=False))
    assert r3.status_code == 200, r3.text
    assert r3.json()["name"] == "Sarah Taylor"
    assert r3.json()["is_active"] is False
    assert _last_audit(db, "testimonial.updated") is not None

    r4 = client.delete(f"{BASE}/{created['id']}", headers=headers)
    assert r4.status_code == 204
    assert _last_audit(db, "testimonial.deleted") is not None
    r5 = client.get(BASE, headers=headers)
    assert all(row["id"] != created["id"] for row in r5.json())


def test_update_missing_row_404(client, admin):
    r = client.patch(f"{BASE}/999999",
                     headers=auth_header(client, admin.email),
                     json=_make_payload())
    assert r.status_code == 404


def test_quote_length_validated(client, admin):
    r = client.post(BASE, headers=auth_header(client, admin.email),
                    json=_make_payload(quote="x" * 2001))
    assert r.status_code == 422


# ----------------------------------------------------------- RBAC

def test_regular_user_forbidden(client, user):
    r = client.post(BASE, headers=auth_header(client, user.email),
                    json=_make_payload())
    assert r.status_code in (401, 403)


def test_anonymous_unauthorized(client):
    assert client.get(BASE).status_code == 401
    assert client.post(BASE, json=_make_payload()).status_code == 401


# ----------------------------------------------------------- public endpoint

def test_public_hides_inactive_and_orders_by_display_order(client, admin):
    headers = auth_header(client, admin.email)
    client.post(BASE, headers=headers,
                json=_make_payload(name="Second", display_order=20))
    client.post(BASE, headers=headers,
                json=_make_payload(name="First", display_order=5))
    client.post(BASE, headers=headers,
                json=_make_payload(name="Hidden", display_order=1,
                                   is_active=False))

    r = client.get(PUBLIC)
    assert r.status_code == 200
    names = [row["name"] for row in r.json()]
    assert "Hidden" not in names
    assert names.index("First") < names.index("Second")
    # Public payload never leaks admin-only fields.
    assert "is_active" not in r.json()[0]


def test_public_endpoint_is_anonymous(client, admin):
    headers = auth_header(client, admin.email)
    client.post(BASE, headers=headers, json=_make_payload())
    r = client.get(PUBLIC)   # no auth header on purpose
    assert r.status_code == 200
    assert len(r.json()) >= 1


# ----------------------------------------------------------- landing knobs

def test_landing_copy_exposes_banner_and_testimonial_knobs(client):
    r = client.get("/api/v1/content/landing")
    assert r.status_code == 200
    body = r.json()
    # Banner defaults: disabled until the admin flips it on.
    assert body["live_banner_enabled"] is False
    assert isinstance(body["live_banner_text"], str)
    assert body["live_banner_font_size"] == 16
    assert body["live_banner_font_style"] == "normal"
    assert body["live_banner_font_color"].startswith("#")
    assert body["live_banner_bg_color"].startswith("#")
    assert body["live_banner_animation"] == "none"
    # Testimonial section defaults: enabled, 6s rotation.
    assert body["testimonials_enabled"] is True
    assert body["testimonials_interval_ms"] == 6000
    assert isinstance(body["testimonials_heading"], str)
