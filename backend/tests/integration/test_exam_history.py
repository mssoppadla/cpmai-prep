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


def test_history_includes_draft_with_status(client, user, sample_exam_set):
    """A live draft IS listed — as status="in_progress" — so the dashboard
    can render a Resume row per set and the attempts manager can show
    every instance. (Contract flipped 2026-08-07; the list used to be
    submitted-only.) Drafts have no submitted_at and are never labeled
    auto-submitted."""
    headers = auth_header(client, user.email)
    client.post(f"/api/v1/exam-sets/{sample_exam_set.slug}/start", headers=headers)
    rows = client.get("/api/v1/exams/attempts", headers=headers).json()
    assert len(rows) == 1
    d = rows[0]
    assert d["status"] == "in_progress"
    assert d["submitted_at"] is None
    assert d["auto_submitted"] is False
    assert d["expires_at"]


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
