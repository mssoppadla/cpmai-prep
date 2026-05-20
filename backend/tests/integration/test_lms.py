"""Integration tests for the LMS foundation (PR #7).

Focused on critical paths rather than exhaustive CRUD enumeration —
the architecture is similar to the CMS PRs so we trust those patterns
where they're identical. Tests here pin:

  - Course CRUD + soft-delete + slug reuse
  - Chapter / lesson / file CRUD
  - Catalog visibility filter (drafts / soft-deleted hidden)
  - Free preview vs paid-lesson body redaction
  - Self-enroll (free) vs refused (paid)
  - Lesson progress upsert + completion calc
  - Quiz config + question + option + attempt scoring
  - Quiz attempt cap
  - RBAC: anon 401, regular user 403 on admin endpoints
  - Audit log on representative writes
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import desc

from app.models.audit_log import AuditLog
from app.models.lms import (
    Chapter, Course, CourseAnnouncement, CourseCategory, Enrollment,
    Lesson, LessonFile, LessonNote, LessonProgress, LmsQuiz,
    LmsQuizAttempt, LmsQuizQuestion, LmsQuizQuestionOption,
)
from tests.conftest import auth_header


ADM = "/api/v1/admin"
PUB = "/api/v1/lms"


# ============================================================ fixtures

@pytest.fixture
def course(db, default_tenant):
    c = Course(
        slug="intro-python", title="Intro to Python",
        is_published=True,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


@pytest.fixture
def chapter(db, course):
    ch = Chapter(course_id=course.id, title="Week 1", position=10)
    db.add(ch); db.commit(); db.refresh(ch)
    return ch


@pytest.fixture
def lesson(db, chapter):
    l = Lesson(
        chapter_id=chapter.id, lesson_type="text",
        title="Welcome", position=10,
        body_blocks=[{"type": "paragraph", "content": "Hello"}],
    )
    db.add(l); db.commit(); db.refresh(l)
    return l


@pytest.fixture
def enrollment(db, user, course):
    e = Enrollment(
        user_id=user.id, course_id=course.id, source="admin_grant",
    )
    db.add(e); db.commit(); db.refresh(e)
    return e


# ============================================================ courses CRUD

def test_course_create_and_get(client, db, admin, default_tenant):
    r = client.post(f"{ADM}/courses",
                    headers=auth_header(client, admin.email),
                    json={"slug": "course-1", "title": "Course 1"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["created_by"] == admin.id
    g = client.get(f"{ADM}/courses/{cid}",
                   headers=auth_header(client, admin.email))
    assert g.status_code == 200
    assert g.json()["slug"] == "course-1"


def test_course_slug_reuse_after_soft_delete(client, db, admin, default_tenant):
    r1 = client.post(f"{ADM}/courses", headers=auth_header(client, admin.email),
                     json={"slug": "x", "title": "X"})
    cid = r1.json()["id"]
    assert client.delete(f"{ADM}/courses/{cid}",
                         headers=auth_header(client, admin.email)).status_code == 204
    # Same slug allowed after soft-delete (partial unique index)
    r2 = client.post(f"{ADM}/courses", headers=auth_header(client, admin.email),
                     json={"slug": "x", "title": "X v2"})
    assert r2.status_code == 201, r2.text


def test_course_duplicate_slug_blocked_when_live(client, db, admin, default_tenant):
    client.post(f"{ADM}/courses", headers=auth_header(client, admin.email),
                json={"slug": "y", "title": "Y"})
    r = client.post(f"{ADM}/courses", headers=auth_header(client, admin.email),
                    json={"slug": "y", "title": "Y2"})
    assert r.status_code == 409


# ============================================================ chapters + lessons + files

def test_create_chapter_and_lesson_and_file(client, db, admin, course):
    r = client.post(f"{ADM}/courses/{course.id}/chapters",
                    headers=auth_header(client, admin.email),
                    json={"title": "Chapter 1"})
    assert r.status_code == 201
    chid = r.json()["id"]
    # auto-position assigned
    assert r.json()["position"] >= 10

    r2 = client.post(f"{ADM}/chapters/{chid}/lessons",
                     headers=auth_header(client, admin.email),
                     json={"lesson_type": "text", "title": "L1"})
    assert r2.status_code == 201
    lid = r2.json()["id"]

    r3 = client.post(f"{ADM}/lessons/{lid}/files",
                     headers=auth_header(client, admin.email),
                     json={"filename": "intro.pdf",
                           "file_url": "https://example.com/intro.pdf",
                           "file_category": "reference"})
    assert r3.status_code == 201
    assert r3.json()["uploaded_by_id"] == admin.id


def test_lesson_position_auto_at_end(client, db, admin, chapter):
    r1 = client.post(f"{ADM}/chapters/{chapter.id}/lessons",
                     headers=auth_header(client, admin.email),
                     json={"lesson_type": "text", "title": "L1"})
    r2 = client.post(f"{ADM}/chapters/{chapter.id}/lessons",
                     headers=auth_header(client, admin.email),
                     json={"lesson_type": "text", "title": "L2"})
    # Second lesson's position should be > first's
    assert r2.json()["position"] > r1.json()["position"]


# ============================================================ public catalog

def test_public_catalog_hides_drafts(client, db, default_tenant):
    db.add(Course(slug="draft", title="Draft", is_published=False))
    db.add(Course(slug="live",  title="Live",  is_published=True))
    db.commit()
    r = client.get(f"{PUB}/courses")
    slugs = [c["slug"] for c in r.json()]
    assert "live" in slugs
    assert "draft" not in slugs


def test_public_catalog_hides_soft_deleted(client, db, default_tenant):
    db.add(Course(slug="rip", title="Rip",
                  is_published=True, is_deleted=True))
    db.add(Course(slug="ok", title="Ok", is_published=True))
    db.commit()
    r = client.get(f"{PUB}/courses")
    slugs = [c["slug"] for c in r.json()]
    assert "ok" in slugs and "rip" not in slugs


def test_public_course_detail_returns_full_tree(client, db, course, chapter, lesson):
    r = client.get(f"{PUB}/courses/{course.slug}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["course"]["slug"] == course.slug
    assert len(body["chapters"]) == 1
    assert body["chapters"][0]["lessons"][0]["title"] == "Welcome"


def test_public_course_redacts_paid_body_for_anon(
    client, db, course, chapter, lesson,
):
    # lesson has body_blocks; default is_free_preview=False
    r = client.get(f"{PUB}/courses/{course.slug}")
    lsn = r.json()["chapters"][0]["lessons"][0]
    # body redacted for non-enrolled anonymous
    assert lsn["body_blocks"] == []
    assert lsn["video_url"] is None


def test_public_course_shows_body_when_free_preview(
    client, db, course, chapter, lesson,
):
    lesson.is_free_preview = True
    db.commit()
    r = client.get(f"{PUB}/courses/{course.slug}")
    lsn = r.json()["chapters"][0]["lessons"][0]
    assert lsn["body_blocks"]


def test_public_course_shows_body_when_enrolled(
    client, db, user, course, chapter, lesson, enrollment,
):
    r = client.get(f"{PUB}/courses/{course.slug}",
                   headers=auth_header(client, user.email))
    lsn = r.json()["chapters"][0]["lessons"][0]
    assert lsn["body_blocks"]
    assert r.json()["is_enrolled"] is True


# ============================================================ enrollment

def test_self_enroll_free_course(client, db, user, default_tenant):
    db.add(Course(slug="freebie", title="Freebie",
                  is_published=True, enrollment_type="free"))
    db.commit()
    r = client.post(f"{PUB}/courses/freebie/enroll",
                    headers=auth_header(client, user.email))
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "free"


def test_self_enroll_paid_course_refused(client, db, user, default_tenant):
    db.add(Course(slug="paid-course", title="Paid",
                  is_published=True, enrollment_type="paid"))
    db.commit()
    r = client.post(f"{PUB}/courses/paid-course/enroll",
                    headers=auth_header(client, user.email))
    assert r.status_code == 422


def test_admin_grant_enrollment(client, db, admin, user, course):
    r = client.post(f"{ADM}/courses/{course.id}/enrollments",
                    headers=auth_header(client, admin.email),
                    json={"user_id": user.id,
                          "grant_reason": "promo trial — comp month"})
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "admin_grant"
    assert r.json()["granted_by_id"] == admin.id


def test_admin_grant_blocks_duplicate(client, db, admin, user, course, enrollment):
    r = client.post(f"{ADM}/courses/{course.id}/enrollments",
                    headers=auth_header(client, admin.email),
                    json={"user_id": user.id,
                          "grant_reason": "twice"})
    assert r.status_code == 409


def test_revoke_enrollment(client, db, admin, enrollment):
    r = client.delete(f"{ADM}/enrollments/{enrollment.id}",
                      headers=auth_header(client, admin.email))
    assert r.status_code == 204
    db.expire_all()
    assert db.get(Enrollment, enrollment.id).revoked_at is not None


# ============================================================ progress + completion

def test_progress_upsert_marks_complete(
    client, db, user, course, chapter, lesson, enrollment,
):
    r = client.put(
        f"{PUB}/enrollments/{enrollment.id}/progress/{lesson.id}",
        headers=auth_header(client, user.email),
        json={"mark_completed": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["completed_at"] is not None
    assert r.json()["first_completed_at"] is not None
    # enrollment.completed_at also set (only one mandatory lesson, completed = 100%)
    db.expire_all()
    assert db.get(Enrollment, enrollment.id).completed_at is not None


def test_progress_video_position(client, db, user, course, chapter, lesson, enrollment):
    r = client.put(
        f"{PUB}/enrollments/{enrollment.id}/progress/{lesson.id}",
        headers=auth_header(client, user.email),
        json={"last_position_seconds": 42, "watch_time_seconds": 50},
    )
    assert r.json()["last_position_seconds"] == 42
    assert r.json()["watch_time_seconds"] == 50
    # Not yet completed
    assert r.json()["completed_at"] is None


# ============================================================ quiz

def _make_quiz(client, db, admin, lesson):
    """Helper: set up a quiz with one single_choice question + 2 options."""
    lesson.lesson_type = "quiz"
    db.commit()
    client.put(f"{ADM}/quizzes/{lesson.id}",
               headers=auth_header(client, admin.email),
               json={"pass_threshold_percent": 50, "attempts_allowed": 2})
    quiz = db.query(LmsQuiz).filter(LmsQuiz.lesson_id == lesson.id).one()
    q = client.post(f"{ADM}/quizzes/{lesson.id}/questions",
                    headers=auth_header(client, admin.email),
                    json={"question_type": "single_choice",
                          "question_text": "2+2?", "points": 1}).json()
    correct = client.post(f"{ADM}/quiz-questions/{q['id']}/options",
                          headers=auth_header(client, admin.email),
                          json={"text": "4", "is_correct": True,
                                "position": 1}).json()
    wrong = client.post(f"{ADM}/quiz-questions/{q['id']}/options",
                        headers=auth_header(client, admin.email),
                        json={"text": "5", "is_correct": False,
                              "position": 2}).json()
    return quiz, q, correct, wrong


def test_quiz_config_upsert(client, db, admin, lesson):
    lesson.lesson_type = "quiz"; db.commit()
    r = client.put(f"{ADM}/quizzes/{lesson.id}",
                   headers=auth_header(client, admin.email),
                   json={"pass_threshold_percent": 80})
    assert r.status_code == 200
    assert r.json()["pass_threshold_percent"] == 80


def test_quiz_config_rejected_for_non_quiz_lesson(client, db, admin, lesson):
    # default lesson is text — not quiz
    r = client.put(f"{ADM}/quizzes/{lesson.id}",
                   headers=auth_header(client, admin.email),
                   json={"pass_threshold_percent": 70})
    assert r.status_code == 422


def test_quiz_attempt_passes_with_correct_answer(
    client, db, admin, user, course, chapter, lesson, enrollment,
):
    quiz, q, correct, _ = _make_quiz(client, db, admin, lesson)
    r = client.post(f"{PUB}/quizzes/{lesson.id}/attempts",
                    headers=auth_header(client, user.email),
                    json={"answers": [
                        {"question_id": q["id"],
                         "selected_option_ids": [correct["id"]]}
                    ]})
    assert r.status_code == 201, r.text
    assert r.json()["passed"] is True
    assert r.json()["percent"] == 100


def test_quiz_attempt_fails_with_wrong_answer(
    client, db, admin, user, course, chapter, lesson, enrollment,
):
    quiz, q, _, wrong = _make_quiz(client, db, admin, lesson)
    r = client.post(f"{PUB}/quizzes/{lesson.id}/attempts",
                    headers=auth_header(client, user.email),
                    json={"answers": [
                        {"question_id": q["id"],
                         "selected_option_ids": [wrong["id"]]}
                    ]})
    assert r.status_code == 201, r.text
    assert r.json()["passed"] is False
    assert r.json()["percent"] == 0


def test_quiz_attempt_cap_enforced(
    client, db, admin, user, course, chapter, lesson, enrollment,
):
    quiz, q, _, wrong = _make_quiz(client, db, admin, lesson)
    # attempts_allowed=2 (set in helper)
    for _ in range(2):
        client.post(f"{PUB}/quizzes/{lesson.id}/attempts",
                    headers=auth_header(client, user.email),
                    json={"answers": [
                        {"question_id": q["id"],
                         "selected_option_ids": [wrong["id"]]}
                    ]})
    r = client.post(f"{PUB}/quizzes/{lesson.id}/attempts",
                    headers=auth_header(client, user.email),
                    json={"answers": [
                        {"question_id": q["id"],
                         "selected_option_ids": [wrong["id"]]}
                    ]})
    assert r.status_code == 409


def test_quiz_attempt_requires_enrollment(client, db, admin, user, lesson, chapter):
    lesson.lesson_type = "quiz"; db.commit()
    r = client.post(f"{PUB}/quizzes/{lesson.id}/attempts",
                    headers=auth_header(client, user.email),
                    json={"answers": []})
    # 402 — subscription/enrollment required
    assert r.status_code == 402


# ============================================================ categories

def test_category_crud(client, db, admin, default_tenant):
    r = client.post(f"{ADM}/course-categories",
                    headers=auth_header(client, admin.email),
                    json={"slug": "ai", "name": "AI"})
    assert r.status_code == 201
    cid = r.json()["id"]
    r2 = client.patch(f"{ADM}/course-categories/{cid}",
                      headers=auth_header(client, admin.email),
                      json={"name": "Artificial Intelligence"})
    assert r2.json()["name"] == "Artificial Intelligence"


def test_link_unlink_course_category(client, db, admin, course):
    cat = CourseCategory(slug="ai", name="AI"); db.add(cat); db.commit(); db.refresh(cat)
    r = client.post(f"{ADM}/courses/{course.id}/categories/{cat.id}",
                    headers=auth_header(client, admin.email))
    assert r.status_code == 204
    # Idempotent
    r2 = client.post(f"{ADM}/courses/{course.id}/categories/{cat.id}",
                     headers=auth_header(client, admin.email))
    assert r2.status_code == 204
    # Unlink
    r3 = client.delete(f"{ADM}/courses/{course.id}/categories/{cat.id}",
                       headers=auth_header(client, admin.email))
    assert r3.status_code == 204


# ============================================================ announcements

def test_announcements_visible_only_to_enrolled(
    client, db, admin, user, course, enrollment,
):
    client.post(f"{ADM}/courses/{course.id}/announcements",
                headers=auth_header(client, admin.email),
                json={"title": "Week 1", "body": "Live this Friday"})
    # Anon: empty
    r_anon = client.get(f"{PUB}/courses/{course.slug}/announcements")
    assert r_anon.json() == []
    # Enrolled: visible
    r_user = client.get(f"{PUB}/courses/{course.slug}/announcements",
                        headers=auth_header(client, user.email))
    assert len(r_user.json()) == 1


# ============================================================ notes (user-owned)

def test_lesson_note_upsert_and_delete(client, db, user, lesson):
    r = client.put(f"{PUB}/lessons/{lesson.id}/note",
                   headers=auth_header(client, user.email),
                   json={"body": "My note"})
    assert r.status_code == 200
    assert r.json()["body"] == "My note"
    # Empty body deletes
    r2 = client.put(f"{PUB}/lessons/{lesson.id}/note",
                    headers=auth_header(client, user.email),
                    json={"body": ""})
    assert r2.json() is None


# ============================================================ reviews

def test_review_upsert(client, db, user, enrollment):
    r = client.put(f"{PUB}/enrollments/{enrollment.id}/review",
                   headers=auth_header(client, user.email),
                   json={"stars": 5, "body": "Great!"})
    assert r.status_code == 200
    assert r.json()["stars"] == 5


# ============================================================ RBAC

def test_admin_endpoint_anon_401(client, db, default_tenant):
    r = client.get(f"{ADM}/courses")
    assert r.status_code == 401


def test_admin_endpoint_user_403(client, db, user, default_tenant):
    r = client.get(f"{ADM}/courses",
                   headers=auth_header(client, user.email))
    assert r.status_code == 403


def test_public_catalog_anonymous_works(client, db, default_tenant):
    r = client.get(f"{PUB}/courses")
    assert r.status_code == 200


# ============================================================ audit

def test_course_create_audit_logged(client, db, admin, default_tenant):
    client.post(f"{ADM}/courses",
                headers=auth_header(client, admin.email),
                json={"slug": "audit-test", "title": "T"})
    row = (db.query(AuditLog)
             .filter(AuditLog.action == "course.created")
             .order_by(desc(AuditLog.id)).first())
    assert row is not None
    assert row.tenant_id == 1
    assert row.user_id == admin.id
