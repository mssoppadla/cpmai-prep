"""Attempt result snapshot: a submitted attempt's review is frozen at
submit time. Editing questions, changing answer keys, or removing
questions from the set afterwards must not rewrite what the candidate
saw — while NEW attempts always sit the current version of the set."""
from app.models.exam_session import ExamSession
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.question import Question, QuestionOption, Difficulty
from app.models.topic import Topic
from tests.conftest import auth_header


def _q(db, *, topic_code: str, domain: str | None, stem: str,
       correct="B") -> Question:
    t = db.query(Topic).filter_by(code=topic_code).first()
    q = Question(stem=stem + " " + "x" * 12, topic_id=t.id,
                 domain=domain, difficulty=Difficulty.EASY, is_active=True)
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


def _admin(db):
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    u = db.query(User).filter_by(email="snapadmin@example.com").first()
    if u:
        return u
    u = User(email="snapadmin@example.com", password_hash=hash_password("x"),
             name="SnapAdmin", role=UserRole.ADMIN)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _take_and_submit(client, headers, slug):
    """Answer q1 correctly (B), q2 wrong (A), leave q3 unanswered."""
    attempt = client.post(f"/api/v1/exam-sets/{slug}/start",
                          headers=headers).json()
    qs = attempt["questions"]
    client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                 headers=headers,
                 json={"question_id": qs[0]["id"], "selected_letter": "B"})
    client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                 headers=headers,
                 json={"question_id": qs[1]["id"], "selected_letter": "A"})
    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=headers)
    assert r.status_code == 200, r.text
    return attempt, r.json()


def _mutate_set(db, es, q1, q2):
    """The edits an admin might make after candidates sat the exam:
    reword q1's stem, flip its answer key to A, move its domain; remove
    q2 from the set entirely."""
    q1.stem = "REWRITTEN stem " + "y" * 12
    q1.domain = "D-V"
    for o in q1.options:
        o.is_correct = (o.option_letter == "A")
        o.text = "changed " + o.option_letter
    db.query(ExamSetQuestion).filter_by(
        exam_set_id=es.id, question_id=q2.id).delete()
    db.commit()


def test_submitted_review_is_frozen_against_later_edits(client, user, db):
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", domain="D-I", stem="Original stem q1")
    q2 = _q(db, topic_code="DU", domain="D-I", stem="Original stem q2")
    q3 = _q(db, topic_code="DU", domain="D-III", stem="Original stem q3")
    es = _set_with(db, _admin(db), "frozen-set", [q1, q2, q3])

    attempt, submitted = _take_and_submit(client, headers, es.slug)
    _mutate_set(db, es, q1, q2)

    r = client.get(f"/api/v1/exams/attempts/{attempt['id']}/result",
                   headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()

    # The snapshot replays the sitting exactly: original stem, original
    # answer key, the removed question still present, original domain.
    by_id = {q["id"]: q for q in result["questions"]}
    assert len(result["questions"]) == 3
    assert by_id[q1.id]["stem"].startswith("Original stem q1")
    assert {o["option_letter"] for o in by_id[q1.id]["options"]
            if o["is_correct"]} == {"B"}
    assert by_id[q1.id]["is_user_correct"] is True
    assert q2.id in by_id                       # removed from set, still shown
    assert by_id[q1.id]["domain"] == "D-I"      # pre-edit domain

    # Counts and score stay coherent with what was sat.
    assert result["score"] == submitted["score"]
    assert result["correct_count"] == 1
    assert result["incorrect_count"] == 1
    assert result["unanswered_count"] == 1
    by_domain = {d["domain"]: d for d in result["by_domain"]}
    assert by_domain["D-I"]["total"] == 2
    assert by_domain["D-III"]["total"] == 1


def test_new_attempt_sits_the_updated_set(client, user, db):
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", domain="D-I", stem="Original stem q1")
    q2 = _q(db, topic_code="DU", domain="D-I", stem="Original stem q2")
    q3 = _q(db, topic_code="DU", domain="D-III", stem="Original stem q3")
    es = _set_with(db, _admin(db), "evolving-set", [q1, q2, q3])

    _take_and_submit(client, headers, es.slug)
    _mutate_set(db, es, q1, q2)

    fresh = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                        headers=headers).json()
    ids = {q["id"] for q in fresh["questions"]}
    assert ids == {q1.id, q3.id}                # q2 gone going forward
    stems = {q["id"]: q["stem"] for q in fresh["questions"]}
    assert stems[q1.id].startswith("REWRITTEN stem")


def test_legacy_attempt_without_snapshot_falls_back_to_live(client, user, db):
    """Attempts submitted before the snapshot column existed keep the
    old behaviour: the review reflects the live question data."""
    headers = auth_header(client, user.email)
    q1 = _q(db, topic_code="BU", domain="D-I", stem="Original stem q1")
    q2 = _q(db, topic_code="DU", domain="D-I", stem="Original stem q2")
    q3 = _q(db, topic_code="DU", domain="D-III", stem="Original stem q3")
    es = _set_with(db, _admin(db), "legacy-snapless", [q1, q2, q3])

    attempt, _ = _take_and_submit(client, headers, es.slug)
    db.query(ExamSession).filter_by(id=attempt["id"]).update(
        {"result_snapshot": None})
    db.commit()
    _mutate_set(db, es, q1, q2)

    result = client.get(f"/api/v1/exams/attempts/{attempt['id']}/result",
                        headers=headers).json()
    by_id = {q["id"]: q for q in result["questions"]}
    assert q2.id not in by_id                   # removed question vanishes
    assert by_id[q1.id]["stem"].startswith("REWRITTEN stem")
    assert by_id[q1.id]["domain"] == "D-V"      # live domain
