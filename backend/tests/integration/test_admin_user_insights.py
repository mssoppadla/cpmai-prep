"""Admin per-user insights: aggregates a single user's exam attempts (count + scores + history),
course time/progress, quiz attempts, and recent activity. Admin-gated."""
from datetime import datetime, timezone

from app.models.exam_session import ExamSession
from tests.conftest import auth_header


def _submitted_attempt(db, user_id, exam_set_id, score, passed):
    now = datetime.now(timezone.utc)
    db.add(ExamSession(user_id=user_id, exam_set_id=exam_set_id, status="submitted",
                       score=score, passed=passed, time_taken_seconds=600,
                       started_at=now, submitted_at=now, expires_at=now))
    db.commit()


def test_user_insights_aggregates_exam_attempts(client, db, admin, user, sample_exam_set):
    _submitted_attempt(db, user.id, sample_exam_set.id, 80, True)
    _submitted_attempt(db, user.id, sample_exam_set.id, 60, False)

    r = client.get(f"/api/v1/admin/users/{user.id}/insights", headers=auth_header(client, admin.email))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["id"] == user.id
    assert data["exam"]["attempt_count"] == 2
    assert data["exam"]["pass_count"] == 1
    assert data["exam"]["best_score"] == 80
    assert data["exam"]["avg_score"] == 70
    assert data["exam"]["attempts"][0]["exam_set"] == "Test Set"
    assert isinstance(data["courses"], list)
    assert "quiz_attempts" in data and isinstance(data["activity"], list)


def test_user_insights_requires_admin(client, user):
    r = client.get(f"/api/v1/admin/users/{user.id}/insights", headers=auth_header(client, user.email))
    assert r.status_code in (401, 403)


def test_user_insights_404_for_missing_user(client, admin):
    r = client.get("/api/v1/admin/users/999999/insights", headers=auth_header(client, admin.email))
    assert r.status_code == 404
