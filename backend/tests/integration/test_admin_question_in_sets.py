"""Cross-set question visibility — `in_sets` on QuestionAdminOut.

Bug-driver: an admin browsing the question bank had no way to see
which sets a question was already in. Tagging the same question into
multiple sets accidentally was easy. The fix exposes `in_sets` on
every QuestionAdminOut payload — three endpoints surface it:

  GET  /admin/questions             list (the picker / bank view)
  GET  /admin/questions/{id}        single question detail
  GET  /admin/exam-sets/{id}/questions   linked-questions for one set

This test asserts:
  - `in_sets` is present on all three endpoints
  - It correctly lists every set the question is tagged into (including
    the set being viewed itself, by design — admin reads "in: this set,
    set 2" and infers what they need)
  - It's empty for an unattached question
  - The bulk-loader makes O(1) DB roundtrips regardless of result size
    (asserted by counting queries via SQLAlchemy event)
  - Sets appear in display_order, then id (deterministic)
"""
from sqlalchemy import event
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.question import Question
from tests.conftest import auth_header


def _make_set(db, *, name, slug, admin, display_order=10) -> ExamSet:
    es = ExamSet(name=name, slug=slug, time_limit_minutes=30,
                 passing_score=70, is_active=True,
                 display_order=display_order, created_by=admin.id)
    db.add(es); db.commit(); db.refresh(es)
    return es


def _link(db, set_id, question_id, admin, position=10):
    db.add(ExamSetQuestion(exam_set_id=set_id, question_id=question_id,
                            position=position, added_by=admin.id))
    db.commit()


# ============================================ GET /admin/questions (list)
def test_list_returns_in_sets_for_attached_questions(
        client, admin, db, sample_question):
    s1 = _make_set(db, name="Set Alpha", slug="set-alpha",
                    admin=admin, display_order=10)
    s2 = _make_set(db, name="Set Beta",  slug="set-beta",
                    admin=admin, display_order=20)
    _link(db, s1.id, sample_question.id, admin)
    _link(db, s2.id, sample_question.id, admin)

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions", headers=h)
    assert r.status_code == 200
    body = r.json()
    rec = next(q for q in body if q["id"] == sample_question.id)
    assert "in_sets" in rec
    slugs = [s["slug"] for s in rec["in_sets"]]
    assert slugs == ["set-alpha", "set-beta"]


def test_list_returns_empty_in_sets_for_unattached_question(
        client, admin, db, sample_question):
    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions", headers=h)
    assert r.status_code == 200
    rec = next(q for q in r.json() if q["id"] == sample_question.id)
    assert rec["in_sets"] == []


def test_list_in_sets_ordered_by_display_order_then_id(
        client, admin, db, sample_question):
    """Determinism matters — the UI shows them in this order verbatim."""
    s_late = _make_set(db, name="Late",   slug="z-late",
                       admin=admin, display_order=99)
    s_first = _make_set(db, name="First", slug="a-first",
                        admin=admin, display_order=1)
    s_middle = _make_set(db, name="Mid",  slug="m-middle",
                         admin=admin, display_order=50)
    for s in (s_late, s_first, s_middle):
        _link(db, s.id, sample_question.id, admin)

    h = auth_header(client, admin.email)
    r = client.get("/api/v1/admin/questions", headers=h)
    rec = next(q for q in r.json() if q["id"] == sample_question.id)
    assert [s["slug"] for s in rec["in_sets"]] == \
           ["a-first", "m-middle", "z-late"]


# ====================================== GET /admin/questions/{id} (single)
def test_get_single_question_returns_in_sets(
        client, admin, db, sample_question):
    s1 = _make_set(db, name="Solo Set", slug="solo-set", admin=admin)
    _link(db, s1.id, sample_question.id, admin)
    h = auth_header(client, admin.email)
    r = client.get(f"/api/v1/admin/questions/{sample_question.id}", headers=h)
    assert r.status_code == 200
    assert [s["slug"] for s in r.json()["in_sets"]] == ["solo-set"]


# ============================== GET /admin/exam-sets/{id}/questions (linked)
def test_linked_endpoint_includes_in_sets_per_question(
        client, admin, db, sample_question):
    """When viewing 'Manage Questions' for Set Alpha, each question row
    should also carry the OTHER sets it's tagged into."""
    s1 = _make_set(db, name="Alpha", slug="alpha", admin=admin)
    s2 = _make_set(db, name="Beta",  slug="beta",  admin=admin)
    _link(db, s1.id, sample_question.id, admin)
    _link(db, s2.id, sample_question.id, admin)

    h = auth_header(client, admin.email)
    r = client.get(f"/api/v1/admin/exam-sets/{s1.id}/questions", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    slugs = [s["slug"] for s in body[0]["question"]["in_sets"]]
    # The viewed set is INCLUDED — the UI's job to dedupe if it cares,
    # but the data should be complete.
    assert sorted(slugs) == ["alpha", "beta"]


# ============================== POST/PATCH responses also surface in_sets
def test_create_question_response_has_empty_in_sets(client, admin, db):
    """A newly-created question is unattached — in_sets should be []
    (not omitted, not null)."""
    h = auth_header(client, admin.email)
    # Need an active topic id — sample_question fixture uses topic 'DU'
    from app.models.topic import Topic
    du = db.query(Topic).filter_by(code="DU").first()
    r = client.post("/api/v1/admin/questions", headers=h, json={
        "stem": "New question?", "topic_id": du.id,
        "difficulty": "easy",
        "options": [
            {"option_letter": "A", "text": "yes", "is_correct": True},
            {"option_letter": "B", "text": "no",  "is_correct": False},
        ],
    })
    assert r.status_code == 201, r.text
    assert r.json()["in_sets"] == []


# ============================== efficiency — no N+1
def test_in_sets_loads_in_constant_db_roundtrips(
        client, admin, db, db_engine, sample_question):
    """The bulk-loader must NOT issue per-question queries. Counting
    SELECTs at the engine level is the most direct way to assert that.

    Setup: one question linked to many sets. The endpoint should issue
    a small constant number of SELECTs (auth → topic seeding skipped →
    questions list → ONE bulk join for in_sets), NOT one-per-question.
    """
    # 5 sets, all linked to the same question
    sets = [_make_set(db, name=f"Set {i}", slug=f"set-{i}",
                       admin=admin, display_order=i)
             for i in range(5)]
    for s in sets:
        _link(db, s.id, sample_question.id, admin)

    # Count SELECT statements during the request only.
    selects: list[str] = []
    def _capture(conn, _cursor, statement, *_args, **_kw):
        if statement.strip().upper().startswith("SELECT"):
            selects.append(statement[:120])
    event.listen(db_engine, "before_cursor_execute", _capture)
    try:
        h = auth_header(client, admin.email)
        r = client.get("/api/v1/admin/questions", headers=h)
    finally:
        event.remove(db_engine, "before_cursor_execute", _capture)

    assert r.status_code == 200
    rec = next(q for q in r.json() if q["id"] == sample_question.id)
    assert len(rec["in_sets"]) == 5

    # Look specifically at the in_sets join — should appear EXACTLY ONCE,
    # not 5 times. Defensive: also assert no per-set lookup.
    join_selects = [s for s in selects if "exam_set_questions" in s.lower()
                                       and "exam_sets" in s.lower()]
    assert len(join_selects) == 1, (
        f"Expected ONE bulk join for in_sets, got {len(join_selects)}: "
        f"{join_selects}")
