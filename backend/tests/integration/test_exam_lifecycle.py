"""The end-to-end exam flow — most important test in this suite.

Verifies (a) answers are NEVER on the wire during attempt, and
(b) full reasoning IS revealed only after submit.
"""
from tests.conftest import auth_header


def test_full_exam_lifecycle(client, user, sample_exam_set):
    headers = auth_header(client, user.email)

    # 1. List sets — public + auth share shape
    r = client.get("/api/v1/exam-sets", headers=headers)
    assert r.status_code == 200
    sets = r.json()
    assert len(sets) == 1
    assert sets[0]["slug"] == "test-set"
    assert sets[0]["question_count"] == 1

    # 2. Start attempt
    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=headers)
    assert r.status_code == 201
    attempt = r.json()
    assert attempt["status"] == "in_progress"
    assert len(attempt["questions"]) == 1

    # 3. CRITICAL: answers must NOT be in the attempt payload.
    q_payload = attempt["questions"][0]
    assert "is_correct" not in str(q_payload)
    assert "reasoning" not in str(q_payload)
    for opt in q_payload["options"]:
        assert set(opt.keys()) == {"option_letter", "text"}, \
            f"Answer leak detected: {opt.keys()}"
    qid = q_payload["id"]

    # 4. Save an (incorrect) answer
    r = client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                     headers=headers,
                     json={"question_id": qid, "selected_letter": "A",
                           "marked_for_review": False})
    assert r.status_code == 204

    # 5. Submit
    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=headers)
    assert r.status_code == 200
    result = r.json()

    # 6. AFTER submit: reasoning IS exposed
    assert result["score"] == 0
    assert result["passed"] is False
    assert result["correct_count"] == 0
    assert result["incorrect_count"] == 1

    rq = result["questions"][0]
    assert rq["is_user_correct"] is False
    options = {o["option_letter"]: o for o in rq["options"]}
    assert options["B"]["is_correct"] is True
    assert "Phase 2" in options["B"]["reasoning"]
    assert options["A"]["selected_by_user"] is True
    assert "Phase 1 defines" in options["A"]["reasoning"]
    assert options["A"]["is_correct"] is False
    # Phase breakdown present
    assert any(p["topic_code"] == "DU" for p in result["by_phase"])
    # Domain breakdown present (what the results screen displays)
    assert result["by_domain"], "expected a by_domain rollup"
    assert all({"domain", "correct", "total", "percent"} <= d.keys()
               for d in result["by_domain"])


def test_cold_load_result_endpoint(client, user, sample_exam_set):
    """Phase 2 endpoint: GET /attempts/{id}/result returns full reasoning."""
    headers = auth_header(client, user.email)

    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=headers)
    attempt_id = r.json()["id"]
    qid = r.json()["questions"][0]["id"]

    client.patch(f"/api/v1/exams/attempts/{attempt_id}/answer", headers=headers,
                 json={"question_id": qid, "selected_letter": "B"})
    client.post(f"/api/v1/exams/attempts/{attempt_id}/submit", headers=headers)

    r = client.get(f"/api/v1/exams/attempts/{attempt_id}/result",
                   headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 100
    assert body["passed"] is True
    rq = body["questions"][0]
    assert rq["is_user_correct"] is True
    correct = next(o for o in rq["options"] if o["is_correct"])
    assert "Phase 2" in correct["reasoning"]


def test_cannot_access_other_users_attempt(client, user, sample_exam_set, db):
    """RBAC: a different user can't view someone else's attempt."""
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    other = User(email="bob@example.com",
                 password_hash=hash_password("password123"),
                 name="Bob", role=UserRole.USER)
    db.add(other); db.commit()

    headers_a = auth_header(client, user.email)
    r = client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start",
                    headers=headers_a)
    attempt_id = r.json()["id"]

    headers_b = auth_header(client, other.email)
    r = client.get(f"/api/v1/exams/attempts/{attempt_id}", headers=headers_b)
    assert r.status_code == 403
