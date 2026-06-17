"""Admin internal-notes on USER contacts (parity with lead notes).

Migration 0035 added ``users.notes`` so the Contacts feed can jot
internal notes on signed-up users, not just landing-form leads.
"""
from tests.conftest import auth_header


def test_update_user_notes_persists(client, db, admin, user):
    headers = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/users/{user.id}/notes",
                     headers=headers, json={"notes": "VIP — called, wants bundle"})
    assert r.status_code == 200, r.text

    db.refresh(user)
    assert user.notes == "VIP — called, wants bundle"


def test_user_notes_surface_in_contacts_feed(client, db, admin, user):
    headers = auth_header(client, admin.email)
    client.patch(f"/api/v1/admin/users/{user.id}/notes",
                 headers=headers, json={"notes": "follow up Monday"})

    r = client.get("/api/v1/admin/leads/contacts?kind=user", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    mine = next((row for row in rows
                 if row["kind"] == "user" and row["id"] == user.id), None)
    assert mine is not None
    assert mine["notes"] == "follow up Monday"


def test_empty_notes_clears(client, db, admin, user):
    headers = auth_header(client, admin.email)
    client.patch(f"/api/v1/admin/users/{user.id}/notes",
                 headers=headers, json={"notes": "temp"})
    r = client.patch(f"/api/v1/admin/users/{user.id}/notes",
                     headers=headers, json={"notes": ""})
    assert r.status_code == 200
    db.refresh(user)
    assert user.notes == ""


def test_user_notes_requires_admin(client, user):
    headers = auth_header(client, user.email)
    r = client.patch(f"/api/v1/admin/users/{user.id}/notes",
                     headers=headers, json={"notes": "nope"})
    assert r.status_code in (401, 403)


def test_user_notes_404_for_missing_user(client, admin):
    headers = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/users/999999/notes",
                     headers=headers, json={"notes": "x"})
    assert r.status_code == 404
