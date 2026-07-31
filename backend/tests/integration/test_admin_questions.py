"""Question CRUD + the strict validation rules."""
from tests.conftest import auth_header


def test_create_question_requires_exactly_one_correct(client, admin, db):
    headers = auth_header(client, admin.email)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()

    # Two correct → reject
    r = client.post("/api/v1/admin/questions", headers=headers, json={
        "stem": "Two-correct test " + "x" * 20,
        "topic_id": du.id,
        "options": [
            {"option_letter": "A", "text": "a", "is_correct": True},
            {"option_letter": "B", "text": "b", "is_correct": True},
        ],
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("validation_failed",)


def test_create_question_rejects_duplicate_letters(client, admin, db):
    headers = auth_header(client, admin.email)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    r = client.post("/api/v1/admin/questions", headers=headers, json={
        "stem": "Dup-letter test " + "x" * 20,
        "topic_id": du.id,
        "options": [
            {"option_letter": "A", "text": "a", "is_correct": True},
            {"option_letter": "A", "text": "a2", "is_correct": False},
        ],
    })
    assert r.status_code == 422


def test_create_question_with_full_metadata(client, admin, db):
    headers = auth_header(client, admin.email)
    from app.models.topic import Topic
    bu = db.query(Topic).filter_by(code="BU").first()
    payload = {
        "stem": "When does CPMAI Phase 1 conclude? " + "x" * 20,
        "topic_id": bu.id,
        "domain": "Business Understanding > Closure",
        "task": "Articulate success criteria",
        "enablers": ["Stakeholder workshops"],
        "remarks": "Foundational.",
        "difficulty": "easy",
        "explanation": "It concludes when KPIs are signed off.",
        "options": [
            {"option_letter": "A", "text": "When KPIs are signed off",
             "is_correct": True, "reasoning": "Correct — Phase 1 ends at signoff."},
            {"option_letter": "B", "text": "When data is collected",
             "is_correct": False, "reasoning": "That's Phase 2's start, not Phase 1's end."},
        ],
        "is_active": True,
    }
    r = client.post("/api/v1/admin/questions", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == payload["domain"]
    assert body["enablers"] == payload["enablers"]
    assert any(o["reasoning"] for o in body["options"])


def test_domain_canonicalized_on_write(client, admin, db):
    """Any accepted spelling of an ECO domain is stored as its code, so
    SQL filters / the editor dropdown / results grouping all agree.
    Unrecognised free-text (previous test) is kept verbatim."""
    headers = auth_header(client, admin.email)
    from app.models.topic import Topic
    bu = db.query(Topic).filter_by(code="BU").first()
    opts = [
        {"option_letter": "A", "text": "a", "is_correct": True},
        {"option_letter": "B", "text": "b", "is_correct": False},
    ]
    r = client.post("/api/v1/admin/questions", headers=headers, json={
        "stem": "Domain canonicalization test " + "x" * 20,
        "topic_id": bu.id,
        "domain": "D-I Trustworthy",   # legacy bulk-import spelling
        "options": opts,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == "D-I"

    # PATCH with the human name → stored as the code too.
    r = client.patch(f"/api/v1/admin/questions/{body['id']}", headers=headers,
                     json={"stem": body["stem"], "topic_id": bu.id,
                           "domain": "Identify Business Needs and Solutions",
                           "options": opts})
    assert r.status_code == 200, r.text
    assert r.json()["domain"] == "D-II"

    from app.models.question import Question
    assert db.get(Question, body["id"]).domain == "D-II"
