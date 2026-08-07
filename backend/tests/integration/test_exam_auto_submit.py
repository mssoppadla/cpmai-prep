"""Time-up auto-submit: a sitting whose clock ran out is finalized with
whatever was answered — never voided. Covers the timer's client-side
auto-submit (submit after expiry), the read-path auto-finalize
(get_attempt / get_result), and legacy 'expired' rows."""
from datetime import datetime, timedelta, timezone

from app.models.exam_session import ExamSession
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.question import Question, QuestionOption, Difficulty
from app.models.topic import Topic
from tests.conftest import auth_header


def _q(db, *, topic_code: str, stem: str, correct="B") -> Question:
    t = db.query(Topic).filter_by(code=topic_code).first()
    q = Question(stem=stem + " " + "x" * 12, topic_id=t.id, domain="D-I",
                 difficulty=Difficulty.EASY, is_active=True)
    q.options = [
        QuestionOption(option_letter="A", text="a", is_correct=(correct == "A")),
        QuestionOption(option_letter="B", text="b", is_correct=(correct == "B")),
    ]
    db.add(q); db.commit(); db.refresh(q)
    return q


def _set_with(db, admin, slug, questions) -> ExamSet:
    es = ExamSet(name=slug.title(), slug=slug, time_limit_minutes=30,
                 passing_score=70, is_active=True, created_by=admin.id)
    db.add(es); db.flush()
    for i, q in enumerate(questions):
        db.add(ExamSetQuestion(exam_set_id=es.id, question_id=q.id,
                               position=i, added_by=admin.id))
    db.commit(); db.refresh(es)
    return es


def _admin(db):
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    u = db.query(User).filter_by(email="autoadmin@example.com").first()
    if u:
        return u
    u = User(email="autoadmin@example.com", password_hash=hash_password("x"),
             name="AutoAdmin", role=UserRole.ADMIN)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _start_answer_expire(client, headers, db, slug, q_answered):
    """Start an attempt, answer one question, then drain the clock
    (simulating the sitting timing out).

    Since the pause-on-leave timer (0046), "time is up" means the
    ACTIVE-TIME BUDGET is exhausted — a past `expires_at` alone is just
    what a paused draft looks like while the candidate is away, and must
    stay resumable. Drain both so the simulation matches the contract.
    """
    attempt = client.post(f"/api/v1/exam-sets/{slug}/start",
                          headers=headers).json()
    client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                 headers=headers,
                 json={"question_id": q_answered, "selected_letter": "B"})
    db.query(ExamSession).filter_by(id=attempt["id"]).update(
        {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=5),
         "remaining_seconds": 0})
    db.commit()
    return attempt


def test_submit_after_expiry_captures_results(client, user, db):
    """The timer's auto-submit fires a second late by nature — it must
    finalize the attempt, not 409."""
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", stem="Answered one")
    q2 = _q(db, topic_code="DU", stem="Never reached")
    es = _set_with(db, _admin(db), "timeup-set", [q1, q2])
    attempt = _start_answer_expire(client, headers, db, es.slug, q1.id)

    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["correct_count"] == 1
    assert result["unanswered_count"] == 1
    assert result["score"] == 50
    # Reported time never exceeds the sitting's limit.
    assert result["time_taken_seconds"] <= 30 * 60

    # Double-submit is still rejected.
    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=headers)
    assert r.status_code == 409


def test_get_attempt_auto_finalizes_timed_out_sitting(client, user, db):
    """Reloading the attempt after time-up finalizes it server-side —
    even if the browser never manages to call submit."""
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", stem="Answered one")
    q2 = _q(db, topic_code="DU", stem="Never reached")
    es = _set_with(db, _admin(db), "timeup-get", [q1, q2])
    attempt = _start_answer_expire(client, headers, db, es.slug, q1.id)

    r = client.get(f"/api/v1/exams/attempts/{attempt['id']}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"

    result = client.get(f"/api/v1/exams/attempts/{attempt['id']}/result",
                        headers=headers).json()
    assert result["correct_count"] == 1
    assert result["unanswered_count"] == 1


def test_get_result_finalizes_legacy_expired_attempt(client, user, db):
    """Rows already stuck in status='expired' (pre-feature) finalize on
    first result view instead of 409-ing."""
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", stem="Answered one")
    q2 = _q(db, topic_code="DU", stem="Never reached")
    es = _set_with(db, _admin(db), "timeup-legacy", [q1, q2])
    attempt = _start_answer_expire(client, headers, db, es.slug, q1.id)
    db.query(ExamSession).filter_by(id=attempt["id"]).update(
        {"status": "expired"})
    db.commit()

    r = client.get(f"/api/v1/exams/attempts/{attempt['id']}/result",
                   headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 50

    db.expire_all()
    assert db.get(ExamSession, attempt["id"]).status == "submitted"


def test_late_answers_still_rejected(client, user, db):
    """Time-up finalizes with what WAS answered — it never accepts new
    answers after the clock."""
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", stem="Answered one")
    q2 = _q(db, topic_code="DU", stem="Late answer target")
    es = _set_with(db, _admin(db), "timeup-late", [q1, q2])
    attempt = _start_answer_expire(client, headers, db, es.slug, q1.id)

    r = client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                     headers=headers,
                     json={"question_id": q2.id, "selected_letter": "B"})
    assert r.status_code == 409
    # ...and the sitting still finalizes with the pre-expiry answers.
    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["correct_count"] == 1