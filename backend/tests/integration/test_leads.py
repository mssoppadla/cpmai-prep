"""Lead capture: anon_id linkage + consent + UTM."""


def test_lead_submit_with_utm_and_consent(client):
    r = client.post("/api/v1/leads", json={
        "email": "marketing@example.com",
        "name": "Marketer",
        "source": "landing_hero",
        "utm": {"source": "google", "campaign": "cpmai-jul"},
        "consent_marketing": True,
        "interests": ["modeling", "exam-prep"],
    })
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert "Thanks" in body["message"]


def test_lead_email_normalized(client, db):
    client.post("/api/v1/leads", json={
        "email": "Mixed@Example.COM", "source": "newsletter",
        "consent_marketing": True,
    })
    from app.models.lead import Lead
    lead = db.query(Lead).order_by(Lead.id.desc()).first()
    assert lead.email == "mixed@example.com"


def test_lead_persists_anon_id_when_cookie_sent(client, db):
    client.cookies.set("aid", "11111111-1111-1111-1111-111111111111")
    client.post("/api/v1/leads", json={
        "email": "anon@example.com", "source": "landing_hero",
    })
    from app.models.lead import Lead
    lead = db.query(Lead).filter_by(email="anon@example.com").first()
    assert lead.anon_id == "11111111-1111-1111-1111-111111111111"
