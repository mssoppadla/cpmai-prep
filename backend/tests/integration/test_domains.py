"""ECO domains: the /content/domains catalog + results-driven, set-scoped
domain-practice drill-down."""
from app.models.exam_set import ExamSet, ExamSetQuestion
from app.models.question import Question, QuestionOption, Difficulty
from app.models.topic import Topic
from tests.conftest import auth_header


def _q(db, *, topic_code: str, domain: str | None, correct="B") -> Question:
    t = db.query(Topic).filter_by(code=topic_code).first()
    q = Question(stem=f"Q {topic_code}/{domain} " + "x" * 12, topic_id=t.id,
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


# ---------------------------------------------------------------- catalog
def test_domains_catalog_lists_five_with_counts(client, db):
    # Two active D-I questions, one inactive D-I, one D-II.
    _q(db, topic_code="BU", domain="D-I")
    _q(db, topic_code="DU", domain="D-I")
    inactive = _q(db, topic_code="DU", domain="D-I")
    inactive.is_active = False; db.commit()
    _q(db, topic_code="BU", domain="D-II")

    r = client.get("/api/v1/content/domains")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [d["code"] for d in rows] == ["D-I", "D-II", "D-III", "D-IV", "D-V"]
    by_code = {d["code"]: d for d in rows}
    assert by_code["D-I"]["active_question_count"] == 2  # inactive excluded
    assert by_code["D-II"]["active_question_count"] == 1
    assert by_code["D-III"]["active_question_count"] == 0
    assert by_code["D-I"]["name"] == "Trustworthy AI"
    assert by_code["D-II"]["phase_codes"] == ["BU"]


# --------------------------------------------------------- domain practice
def test_domain_practice_scopes_to_one_domain(client, user, db):
    headers = auth_header(client, user.email)
    qs = [
        _q(db, topic_code="BU", domain="D-I", correct="B"),
        _q(db, topic_code="DU", domain="D-I", correct="B"),
        _q(db, topic_code="DU", domain="D-III", correct="B"),  # other domain
    ]
    es = _set_with(db, _admin(db), "mixed-set", qs)

    # Start a D-I drill — only the two D-I questions are in scope.
    r = client.post(f"/api/v1/exam-sets/{es.slug}/practice/D-I/start",
                    headers=headers)
    assert r.status_code == 201, r.text
    attempt = r.json()
    assert len(attempt["questions"]) == 2
    assert {q["domain"] for q in attempt["questions"]} == {"D-I"}
    assert "Practice: Trustworthy AI" in attempt["exam_set"]["name"]

    # Answer both correctly and submit.
    for q in attempt["questions"]:
        client.patch(f"/api/v1/exams/attempts/{attempt['id']}/answer",
                     headers=headers,
                     json={"question_id": q["id"], "selected_letter": "B"})
    r = client.post(f"/api/v1/exams/attempts/{attempt['id']}/submit",
                    headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["score"] == 100
    assert result["practice_domain"] == "D-I"
    assert result["exam_set_slug"] == es.slug
    # by_domain only covers the practiced domain.
    assert [d["domain"] for d in result["by_domain"]] == ["D-I"]
    assert result["by_domain"][0]["total"] == 2
    assert result["by_domain"][0]["practiceable"] is True


def test_domain_practice_rejects_empty_domain(client, user, db):
    headers = auth_header(client, user.email)
    qs = [_q(db, topic_code="BU", domain="D-II")]
    es = _set_with(db, _admin(db), "d2-only", qs)
    # No D-I questions in this set → conflict.
    r = client.post(f"/api/v1/exam-sets/{es.slug}/practice/D-I/start",
                    headers=headers)
    assert r.status_code == 409, r.text


def test_domain_practice_unknown_domain_404(client, user, db):
    headers = auth_header(client, user.email)
    es = _set_with(db, _admin(db), "any-set",
                   [_q(db, topic_code="BU", domain="D-II")])
    r = client.post(f"/api/v1/exam-sets/{es.slug}/practice/D-99/start",
                    headers=headers)
    assert r.status_code == 404, r.text


def test_full_sitting_unaffected_by_practice_session(client, user, db):
    """A domain drill and a full sitting on the same set are distinct
    sessions — starting one never resumes the other."""
    headers = auth_header(client, user.email)
    qs = [
        _q(db, topic_code="BU", domain="D-I"),
        _q(db, topic_code="DU", domain="D-III"),
    ]
    es = _set_with(db, _admin(db), "both-set", qs)

    practice = client.post(f"/api/v1/exam-sets/{es.slug}/practice/D-I/start",
                           headers=headers).json()
    full = client.post(f"/api/v1/exam-sets/{es.slug}/start",
                       headers=headers).json()
    assert practice["id"] != full["id"]
    assert len(practice["questions"]) == 1   # D-I only
    assert len(full["questions"]) == 2       # whole set


# --------------------------------------------------------------- helpers
def _admin(db):
    from app.models.user import User, UserRole
    from app.core.security import hash_password
    u = db.query(User).filter_by(email="setadmin@example.com").first()
    if u:
        return u
    u = User(email="setadmin@example.com", password_hash=hash_password("x"),
             name="SetAdmin", role=UserRole.ADMIN)
    db.add(u); db.commit(); db.refresh(u)
    return u
