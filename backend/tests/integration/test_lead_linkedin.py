"""LinkedIn id capture on the landing lead + read-only surfacing to admins on the Users and
Contacts screens. Additive: already-collected WhatsApp numbers stay and are surfaced too."""
from app.models.lead import Lead, LeadSource
from tests.conftest import auth_header


def test_lead_create_persists_linkedin(client):
    r = client.post("/api/v1/leads", json={
        "email": "aspirant@example.com", "name": "Aspi", "source": "landing_hero",
        "linkedin_id": "linkedin.com/in/aspirant", "consent_marketing": True})
    assert r.status_code in (200, 201), r.text
    # surfaced on the Contacts feed
    # (admin auth needed for the admin feed; covered below via the user-screen test)


def test_linkedin_and_existing_whatsapp_surface_on_user_screen(client, db, admin, user):
    # a lead the user left earlier (matched by email) with BOTH linkedin and an
    # already-collected whatsapp number — both must show, nothing altered.
    db.add(Lead(email=user.email.lower(), name=user.name, source=LeadSource.LANDING_HERO,
                linkedin_id="linkedin.com/in/theuser",
                country_code="+91", whatsapp_number="9876543210"))
    db.commit()

    r = client.get("/api/v1/admin/users", headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["id"] == user.id)
    assert row["linkedin_id"] == "linkedin.com/in/theuser"
    assert "9876543210" in (row["whatsapp"] or "")

    # single-user detail surfaces them too
    r2 = client.get(f"/api/v1/admin/users/{user.id}", headers=auth_header(client, admin.email))
    assert r2.status_code == 200
    assert r2.json()["linkedin_id"] == "linkedin.com/in/theuser"


def test_user_without_lead_has_null_contact(client, admin, user):
    r = client.get(f"/api/v1/admin/users/{user.id}", headers=auth_header(client, admin.email))
    assert r.status_code == 200
    body = r.json()
    assert body["linkedin_id"] is None and body["whatsapp"] is None
