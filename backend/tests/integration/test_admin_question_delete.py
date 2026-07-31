"""Question deletion with attempt history + bulk delete.

Deleting a question used to 409 the moment any candidate had answered
it (FK from exam_attempt_answers with no cascade). With result
snapshots (0043/0044) the references are safe to clean up: submitted
attempts read their review from the frozen snapshot, never from answer
rows."""
from app.models.exam_session import ExamAttemptAnswer
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


def _set_with(db, admin, slug: str, questions) -> ExamSet:
    es = ExamSet(name=slug.title(), slug=slug, time_limit_minutes=30,
                 passing_score=70, is_active=True, created_by=admin.id)
    db.add(es); db.flush()
    for i, q in enumerate(questions):
        db.add(ExamSetQuestion(exam_set_id=es.id, question_id=q.id,
                               position=i, added_by=admin.id))
    db.commit(); db.refresh(es)
    return es


def test_delete_question_with_attempt_history(client, admin, user, db):
    """The exact prod failure: candidate answered the question, admin
    deletes it → must succeed, and the candidate's frozen review must
    still show the full sitting."""
    user_h = auth_header(client, user.email)
    admin_h = auth_header(client, admin.email)
    q1 = _q(db, topic_code="BU", stem="Keep me")
    q2 = _q(db, topic_code="DU", stem="Delete me")
    # Plain ints: after the delete, attribute access on the ORM
    # instances would raise ObjectDeletedError.
    q1_id, q2_id = q1.id, q2.id
    es = _set_with(db, admin, "del-history-set", [q1, q2])
    slug = es.slug

    attempt = client.post(f"/api/v1/exam-sets/{slug}/start",
                          headers=user_h).json()
    client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                 headers=user_h,
                 json={"question_id": q2_id, "selected_letter": "B"})
    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=user_h)
    assert r.status_code == 200, r.text

    r = client.delete(f"/api/v1/admin/questions/{q2_id}", headers=admin_h)
    assert r.status_code == 204, r.text

    db.expire_all()
    assert db.query(Question.id).filter_by(id=q2_id).first() is None
    assert db.query(ExamAttemptAnswer).filter_by(question_id=q2_id).count() == 0

    # Frozen review untouched — the deleted question still renders.
    result = client.get(f"/api/v1/exams/attempts/{attempt['id']}/result",
                        headers=user_h).json()
    assert {q["id"] for q in result["questions"]} == {q1_id, q2_id}

    # New attempts sit the set without it.
    fresh = client.post(f"/api/v1/exam-sets/{slug}/start",
                        headers=user_h).json()
    assert {q["id"] for q in fresh["questions"]} == {q1_id}


def test_bulk_delete_questions(client, admin, db):
    admin_h = auth_header(client, admin.email)
    qs = [_q(db, topic_code="BU", stem=f"Bulk {i}") for i in range(3)]
    ids = [q.id for q in qs]
    _set_with(db, admin, "bulk-del-set", qs)

    r = client.post("/api/v1/admin/questions/bulk-delete", headers=admin_h,
                    json={"ids": [ids[0], ids[1], 999999]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 2
    assert sorted(body["ids"]) == sorted(ids[:2])
    assert body["missing"] == [999999]

    db.expire_all()
    remaining = {q.id for q in db.query(Question).all()
                 if q.stem.startswith("Bulk")}
    assert remaining == {ids[2]}
    # Set links for the deleted rows are gone too (DB cascade).
    assert db.query(ExamSetQuestion).filter(
        ExamSetQuestion.question_id.in_(ids[:2])).count() == 0


def test_bulk_delete_requires_admin(client, user, db):
    r = client.post("/api/v1/admin/questions/bulk-delete",
                    headers=auth_header(client, user.email),
                    json={"ids": [1]})
    assert r.status_code in (401, 403), r.text


def test_bulk_delete_rejects_empty_ids(client, admin, db):
    r = client.post("/api/v1/admin/questions/bulk-delete",
                    headers=auth_header(client, admin.email),
                    json={"ids": []})
    assert r.status_code == 422, r.text
