"""Exam history — GET /exams/attempts lists a signed-in learner's past
submitted attempts (so they can revisit their per-domain results)."""
from tests.conftest import auth_header


def _start_submit(client, headers, slug, answer="B"):
    a = client.post(f"/api/v1/exam-sets/{slug}/start", headers=headers).json()
    qid = a["questions"][0]["id"]
    client.patch(f"/api/v1/exams/attempts/{a['id']}/answer", headers=headers,
                 json={"question_id": qid, "selected_letter": answer})
    client.post(f"/api/v1/exams/attempts/{a['id']}/submit", headers=headers)
    return a["id"]


def test_history_lists_submitted_attempt(client, user, sample_exam_set):
    headers = auth_header(client, user.email)
    aid = _start_submit(client, headers, sample_exam_set.slug, answer="B")

    r = client.get("/api/v1/exams/attempts", headers=headers)
    assert r.status_code == 200, r.text
    hist = r.json()
    assert len(hist) == 1
    h = hist[0]
    assert h["id"] == aid
    assert h["exam_set_slug"] == sample_exam_set.slug
    assert h["exam_set_name"] == sample_exam_set.name
    assert h["total_questions"] == 1
    assert h["correct_count"] == 1          # B is the correct option in the fixture
    assert h["practice_domain"] is None
    assert h["submitted_at"]


def test_history_excludes_in_progress(client, user, sample_exam_set):
    headers = auth_header(client, user.email)
    client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start", headers=headers)
    # Not submitted yet → not in history.
    assert client.get("/api/v1/exams/attempts", headers=headers).json() == []


def test_history_requires_signed_in_user(client):
    # Anonymous (no Authorization header) is rejected — history is account-bound.
    assert client.get("/api/v1/exams/attempts").status_code in (401, 403)


def test_history_is_scoped_per_user(client, user, admin, sample_exam_set):
    uh = auth_header(client, user.email)
    _start_submit(client, uh, sample_exam_set.slug)
    # A different signed-in user never sees someone else's attempts.
    ah = auth_header(client, admin.email)
    assert client.get("/api/v1/exams/attempts", headers=ah).json() == []
    # The owner still sees exactly one.
    assert len(client.get("/api/v1/exams/attempts", headers=uh).json()) == 1
