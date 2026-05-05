"""RBAC: regular users cannot reach /admin/* even if they know the URLs."""
from tests.conftest import auth_header


def test_user_cannot_list_questions(client, user):
    headers = auth_header(client, user.email)
    r = client.get("/api/v1/admin/questions", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_user_cannot_create_question(client, user):
    headers = auth_header(client, user.email)
    r = client.post("/api/v1/admin/questions", headers=headers, json={
        "stem": "x" * 20, "topic_id": 1,
        "options": [
            {"option_letter": "A", "text": "a", "is_correct": True},
            {"option_letter": "B", "text": "b", "is_correct": False},
        ],
    })
    assert r.status_code == 403


def test_admin_can_list_questions(client, admin, sample_question):
    headers = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions", headers=headers)
    assert r.status_code == 200
    assert any(q["id"] == sample_question.id for q in r.json())


def test_only_super_admin_can_change_role(client, admin, user):
    headers = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/users/{user.id}/role?role=admin",
                     headers=headers)
    assert r.status_code == 403
