"""Multi-choice question lifecycle: validation, attempt, scoring, result.

Single-choice (one correct, radio in UI) is the historical default.
Multi-choice questions have ≥2 correct options, the learner picks all
that apply (checkboxes), scoring is exact-set match (all-or-nothing).

Coverage:
  - Admin validator
      multi_choice with <2 correct → 422
      multi_choice with ALL correct → 422 (must have 1 wrong option)
      multi_choice with 2 correct + 1 wrong → 201
  - Save answer wire shape
      single_choice + selected_letters payload → 409 (mismatch)
      multi_choice + selected_letter payload → 409
      multi_choice + selected_letters list → persists sorted+deduped
  - Scoring matrix (multi_choice)
      all correct selected, no wrong       → score=100
      missing one correct                  → score=0
      one correct + one wrong              → score=0
      empty                                → unanswered
  - QuestionAttemptView returns question_type so frontend renders
    radio vs checkbox correctly.
  - QuestionResultView marks selected_by_user true for each picked letter.
"""
from app.models.question import (
    Question, QuestionOption, Difficulty, QuestionType,
)
from app.models.exam_set import ExamSet, ExamSetQuestion
from tests.conftest import auth_header


# ===================================================== admin validation
def test_create_multi_choice_question_with_2_correct_succeeds(client, admin, db):
    h = auth_header(client, admin.email)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    r = client.post("/api/v1/admin/questions", headers=h, json={
        "stem": "Which phases involve data work?", "topic_id": du.id,
        "difficulty": "easy", "question_type": "multi_choice",
        "options": [
            {"option_letter": "A", "text": "Data Understanding", "is_correct": True},
            {"option_letter": "B", "text": "Data Preparation",   "is_correct": True},
            {"option_letter": "C", "text": "Modeling",           "is_correct": False},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["question_type"] == "multi_choice"


def test_create_multi_choice_with_only_1_correct_rejected(client, admin, db):
    """A 'multi-choice' question with one correct is structurally
    single_choice — the validator nudges the admin to fix the type."""
    h = auth_header(client, admin.email)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    r = client.post("/api/v1/admin/questions", headers=h, json={
        "stem": "Bad multi", "topic_id": du.id,
        "difficulty": "easy", "question_type": "multi_choice",
        "options": [
            {"option_letter": "A", "text": "right", "is_correct": True},
            {"option_letter": "B", "text": "wrong", "is_correct": False},
        ],
    })
    assert r.status_code == 422
    assert "at least 2" in r.json()["error"]["message"].lower()


def test_create_multi_choice_with_all_correct_rejected(client, admin, db):
    """A question where every option is correct is unanswerable wrong —
    nothing for scoring to differentiate."""
    h = auth_header(client, admin.email)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    r = client.post("/api/v1/admin/questions", headers=h, json={
        "stem": "All correct", "topic_id": du.id,
        "difficulty": "easy", "question_type": "multi_choice",
        "options": [
            {"option_letter": "A", "text": "yes",  "is_correct": True},
            {"option_letter": "B", "text": "also", "is_correct": True},
        ],
    })
    assert r.status_code == 422
    assert "incorrect" in r.json()["error"]["message"].lower()


def test_single_choice_default_preserved_when_type_omitted(client, admin, db):
    """Backward compat: omitting question_type defaults to single_choice."""
    h = auth_header(client, admin.email)
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    r = client.post("/api/v1/admin/questions", headers=h, json={
        "stem": "Default type test", "topic_id": du.id,
        "difficulty": "easy",
        "options": [
            {"option_letter": "A", "text": "yes", "is_correct": True},
            {"option_letter": "B", "text": "no",  "is_correct": False},
        ],
    })
    assert r.status_code == 201
    assert r.json()["question_type"] == "single_choice"


# ===================================================== fixture: multi q
def _make_multi_question(db, admin, *, correct=("A", "B"),
                          letters=("A", "B", "C", "D")) -> Question:
    """Create a multi_choice question with the given correct set."""
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    q = Question(
        stem="Pick all that apply.", topic_id=du.id,
        domain="Data Understanding", difficulty=Difficulty.MEDIUM,
        question_type=QuestionType.MULTI_CHOICE,
        is_active=True,
    )
    q.options = [
        QuestionOption(option_letter=L, text=f"opt {L}",
                        is_correct=(L in correct))
        for L in letters
    ]
    db.add(q); db.commit(); db.refresh(q)
    return q


def _make_set_with_question(db, admin, q: Question) -> ExamSet:
    es = ExamSet(name=f"set-{q.id}", slug=f"set-q{q.id}",
                  time_limit_minutes=30, passing_score=70,
                  is_active=True, created_by=admin.id)
    db.add(es); db.flush()
    db.add(ExamSetQuestion(exam_set_id=es.id, question_id=q.id,
                            position=10, added_by=admin.id))
    db.commit(); db.refresh(es)
    return es


# ===================================================== save_answer wire
def test_save_answer_multi_with_single_letter_payload_rejected(
        client, db, user, admin, sample_question):
    """sample_question is single_choice. Sending a multi-style payload
    must be rejected so future bugs don't silently coerce."""
    es = _make_set_with_question(db, admin, sample_question)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    attempt_id = start.json()["id"]
    r = client.patch(f"/api/v1/exams/attempts/{attempt_id}/answer",
                     headers=h, json={
        "question_id": sample_question.id,
        "selected_letters": ["A", "B"],   # wrong shape for single_choice
    })
    assert r.status_code == 409, r.text
    assert "single-choice" in r.json()["error"]["message"].lower()


def test_save_answer_multi_persists_sorted_deduped(
        client, db, user, admin):
    multi_q = _make_multi_question(db, admin, correct=("A", "C"))
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    attempt_id = start.json()["id"]
    r = client.patch(f"/api/v1/exams/attempts/{attempt_id}/answer",
                     headers=h, json={
        "question_id": multi_q.id,
        "selected_letters": ["C", "A", "C"],  # unsorted + dup
    })
    assert r.status_code == 204, r.text
    from app.models.exam_session import ExamAttemptAnswer
    ans = (db.query(ExamAttemptAnswer)
           .filter_by(exam_session_id=attempt_id,
                       question_id=multi_q.id).first())
    assert ans.selected_letters == ["A", "C"]   # sorted + deduped
    assert ans.selected_letter is None


# ===================================================== scoring matrix
def test_multi_score_all_correct_no_wrong(
        client, db, user, admin):
    """User picks exactly the correct set → score=100."""
    multi_q = _make_multi_question(db, admin, correct=("A", "B"))
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    aid = start.json()["id"]
    client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=h, json={
        "question_id": multi_q.id, "selected_letters": ["A", "B"]})
    submit = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=h)
    assert submit.json()["score"] == 100
    assert submit.json()["correct_count"] == 1


def test_multi_score_missing_one_correct(client, db, user, admin):
    """User picks only some of the correct set → score=0 (no partial)."""
    multi_q = _make_multi_question(db, admin, correct=("A", "B", "C"))
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    aid = start.json()["id"]
    client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=h, json={
        "question_id": multi_q.id, "selected_letters": ["A", "B"]})
    submit = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=h)
    assert submit.json()["score"] == 0
    assert submit.json()["incorrect_count"] == 1


def test_multi_score_correct_plus_extra_wrong(client, db, user, admin):
    """User picks all correct AND one wrong → score=0 (set mismatch)."""
    multi_q = _make_multi_question(db, admin, correct=("A", "B"))
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    aid = start.json()["id"]
    client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=h, json={
        "question_id": multi_q.id, "selected_letters": ["A", "B", "D"]})
    submit = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=h)
    assert submit.json()["score"] == 0


def test_multi_score_empty_selection_unanswered(client, db, user, admin):
    """User saves an empty list → counts as unanswered, not wrong."""
    multi_q = _make_multi_question(db, admin, correct=("A", "B"))
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    aid = start.json()["id"]
    client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=h, json={
        "question_id": multi_q.id, "selected_letters": []})
    submit = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=h)
    body = submit.json()
    assert body["unanswered_count"] == 1
    assert body["correct_count"] == 0


# ===================================================== view shapes
def test_attempt_view_includes_question_type(client, db, user, admin):
    multi_q = _make_multi_question(db, admin)
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    body = start.json()
    qview = next(q for q in body["questions"] if q["id"] == multi_q.id)
    assert qview["question_type"] == "multi_choice"


def test_result_view_marks_each_selected_letter(client, db, user, admin):
    """In multi mode, every letter the user picked must be flagged
    selected_by_user=true. The frontend uses this to highlight all
    user choices on the result page."""
    multi_q = _make_multi_question(db, admin, correct=("A", "C"))
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    aid = start.json()["id"]
    client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=h, json={
        "question_id": multi_q.id, "selected_letters": ["A", "B"]})
    submit = client.post(f"/api/v1/exams/attempts/{aid}/submit", headers=h)
    qres = next(q for q in submit.json()["questions"]
                if q["id"] == multi_q.id)
    selected_letters = {o["option_letter"] for o in qres["options"]
                         if o["selected_by_user"]}
    assert selected_letters == {"A", "B"}
    correct_letters = {o["option_letter"] for o in qres["options"]
                        if o["is_correct"]}
    assert correct_letters == {"A", "C"}
    assert qres["question_type"] == "multi_choice"


# ===================================================== user_answers map
def test_serialize_attempt_user_answers_uses_comma_for_multi(
        client, db, user, admin):
    """Wire shape stays `dict[int, str | None]`. For multi questions,
    the value is a comma-joined sorted list of selected letters so the
    frontend doesn't need a type-discriminated union."""
    multi_q = _make_multi_question(db, admin)
    es = _make_set_with_question(db, admin, multi_q)
    h = auth_header(client, user.email)
    start = client.post(f"/api/v1/exam-sets/{es.slug}/start", headers=h)
    aid = start.json()["id"]
    client.patch(f"/api/v1/exams/attempts/{aid}/answer", headers=h, json={
        "question_id": multi_q.id, "selected_letters": ["B", "A"]})
    # GET the attempt to read back the serialized form
    get_r = client.get(f"/api/v1/exams/attempts/{aid}", headers=h)
    user_answers = get_r.json()["user_answers"]
    assert user_answers[str(multi_q.id)] == "A,B"
