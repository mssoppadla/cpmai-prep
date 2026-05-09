"""GET /admin/questions?tagged=any|none filter.

Companion to the cross-set visibility feature. Two states matter to
admin operators:

  - `tagged=any`  — questions already in ≥1 exam set. Useful when the
                     admin wants to dedupe or audit existing tags.
  - `tagged=none` — orphan questions never linked anywhere. Useful for
                     "what's in the bank but unused yet?"

Composes with the existing topic/domain/search filters via a single
EXISTS subquery — no result-set inflation, no Python-side post-filter.
"""
import pytest
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.question import Question, QuestionOption, Difficulty
from tests.conftest import auth_header


@pytest.fixture
def two_questions_one_tagged(db, admin, sample_question):
    """sample_question is left orphaned. A second question gets tagged
    into a fresh set so we have one of each state."""
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    tagged = Question(
        stem="Tagged question.", topic_id=du.id,
        difficulty=Difficulty.EASY, is_active=True,
    )
    tagged.options = [
        QuestionOption(option_letter="A", text="x", is_correct=True),
        QuestionOption(option_letter="B", text="y", is_correct=False),
    ]
    db.add(tagged); db.commit(); db.refresh(tagged)

    es = ExamSet(name="Holder Set", slug="holder-set",
                  time_limit_minutes=30, passing_score=70,
                  is_active=True, created_by=admin.id)
    db.add(es); db.flush()
    db.add(ExamSetQuestion(exam_set_id=es.id, question_id=tagged.id,
                            position=10, added_by=admin.id))
    db.commit()
    return {"orphan": sample_question.id, "tagged": tagged.id}


def test_filter_omitted_returns_all(client, admin, two_questions_one_tagged):
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions", headers=h)
    assert r.status_code == 200
    ids = {q["id"] for q in r.json()}
    assert two_questions_one_tagged["orphan"] in ids
    assert two_questions_one_tagged["tagged"] in ids


def test_filter_tagged_any_excludes_orphans(client, admin, two_questions_one_tagged):
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions?tagged=any", headers=h)
    assert r.status_code == 200
    ids = {q["id"] for q in r.json()}
    assert two_questions_one_tagged["tagged"] in ids
    assert two_questions_one_tagged["orphan"] not in ids


def test_filter_tagged_none_returns_only_orphans(client, admin, two_questions_one_tagged):
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions?tagged=none", headers=h)
    assert r.status_code == 200
    ids = {q["id"] for q in r.json()}
    assert two_questions_one_tagged["orphan"] in ids
    assert two_questions_one_tagged["tagged"] not in ids


def test_filter_invalid_value_rejected(client, admin):
    """Pattern guard on the query param surfaces a 422 for typos —
    catches frontend bugs that send `tagged=true` or similar."""
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions?tagged=yes", headers=h)
    assert r.status_code == 422


def test_filter_composes_with_search(client, admin, db, two_questions_one_tagged):
    """Filter must AND with the search predicate, not replace it."""
    h = auth_header(client, admin.email)
    # Search for "Tagged" — only matches the tagged question's stem.
    # With tagged=any, expect just that one row.
    r = client.get("/api/v1/admin/questions?q=Tagged&tagged=any", headers=h)
    ids = {q["id"] for q in r.json()}
    assert ids == {two_questions_one_tagged["tagged"]}

    # Same search but tagged=none → empty (the matching question is tagged)
    r2 = client.get("/api/v1/admin/questions?q=Tagged&tagged=none", headers=h)
    assert r2.json() == []
