"""Public LMS endpoints — end-user facing routes.

Mounted under /api/v1/lms. Auth is optional (resolved via
``get_optional_user``). Behaviour cascades on auth state:

  anon         → catalog + course detail (titles only, free-preview lessons)
  authenticated → own enrollments + per-enrollment progress reads
  enrolled     → full lesson bodies, file URLs, notes, reviews, quiz attempts

The endpoints intentionally don't issue signed-URLs for files yet —
that's PR #9's job once R2 is wired up. For now ``file_url`` from
admin uploads is returned as-is.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_current_user, get_db, get_optional_user
from app.core.exceptions import (
    ConflictError, NotFoundError, SubscriptionRequiredError,
    UnauthorizedError, ValidationError,
)
from app.core.tenant import get_current_tenant_id
from app.models.lms import (
    Chapter, Course, CourseAnnouncement, CourseReview,
    Enrollment, Lesson, LessonFile, LessonNote, LessonProgress,
    LmsQuiz, LmsQuizAttempt, LmsQuizQuestion, LmsQuizQuestionOption,
)
from app.models.user import User
from app.schemas.lms import (
    CourseAnnouncementOut, CoursePublicOut, CourseReviewOut,
    CourseReviewUpsertIn, EnrollmentOut, LessonFileOut, LessonNoteOut,
    LessonNoteUpsertIn, LessonProgressOut, LessonProgressUpdateIn,
    LessonPublicOut, QuizAttemptOut, QuizAttemptSubmitIn, QuizQuestionOut,
)
from app.services.lms.scoring import (
    next_attempt_number, recalculate_completion, score_attempt,
)


router = APIRouter()


# ============================================================ helpers

def _live_course_scope(db: Session):
    return db.query(Course).filter(
        Course.tenant_id == get_current_tenant_id(),
        Course.is_published.is_(True),
        Course.is_deleted.is_(False),
    )


def _active_enrollment(db: Session, user: User | None, course_id: int) -> Enrollment | None:
    if user is None:
        return None
    return db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.course_id == course_id,
        Enrollment.revoked_at.is_(None),
        Enrollment.tenant_id == get_current_tenant_id(),
    ).first()


def _redact_lesson(lsn: Lesson, is_enrolled: bool) -> LessonPublicOut:
    """Build a public lesson payload. For non-enrolled users, lesson
    body / video_url are nulled unless the lesson is free_preview."""
    show_body = is_enrolled or lsn.is_free_preview
    out = LessonPublicOut.model_validate(lsn)
    if not show_body:
        out.video_url = None
        out.body_blocks = []
    return out


# ============================================================ CATALOG

@router.get("/courses", response_model=list[CoursePublicOut])
def list_public_courses(
    db: Session = Depends(get_db),
    difficulty: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Public catalog. Filters: difficulty. Ordered by display_order."""
    q = _live_course_scope(db)
    if difficulty:
        q = q.filter(Course.difficulty == difficulty)
    return (q.order_by(Course.display_order, Course.id)
            .offset(offset).limit(limit).all())


@router.get("/courses/{slug}")
def get_public_course(
    slug: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Full course detail — course + chapters + lessons + files.
    Lesson bodies redacted for non-enrolled users (unless free_preview)."""
    c = _live_course_scope(db).filter(Course.slug == slug).first()
    if not c:
        raise NotFoundError("Course not found")
    enrolled = _active_enrollment(db, user, c.id) is not None

    chapters = list(db.query(Chapter).filter(
        Chapter.course_id == c.id,
        Chapter.is_published.is_(True),
        Chapter.is_deleted.is_(False),
    ).order_by(Chapter.position, Chapter.id).all())

    lessons_by_ch: dict[int, list[Lesson]] = {ch.id: [] for ch in chapters}
    for lsn in db.query(Lesson).filter(
        Lesson.chapter_id.in_([ch.id for ch in chapters]) if chapters else False,
        Lesson.is_published.is_(True),
        Lesson.is_deleted.is_(False),
    ).order_by(Lesson.chapter_id, Lesson.position).all():
        lessons_by_ch.setdefault(lsn.chapter_id, []).append(lsn)

    # All files for ALL lessons in this course (1 query, cheap)
    lesson_ids = [l.id for lessons in lessons_by_ch.values() for l in lessons]
    files_by_lesson: dict[int, list[LessonFile]] = {}
    if lesson_ids:
        for f in db.query(LessonFile).filter(LessonFile.lesson_id.in_(lesson_ids)).all():
            files_by_lesson.setdefault(f.lesson_id, []).append(f)

    return {
        "course": CoursePublicOut.model_validate(c).model_dump(),
        "is_enrolled": enrolled,
        "chapters": [
            {
                "id": ch.id,
                "title": ch.title,
                "description": ch.description,
                "position": ch.position,
                "is_mandatory": ch.is_mandatory,
                "lessons": [
                    {
                        **_redact_lesson(lsn, enrolled).model_dump(),
                        "files": [
                            LessonFileOut.model_validate(f).model_dump()
                            for f in sorted(files_by_lesson.get(lsn.id, []),
                                            key=lambda x: (x.position, x.id))
                        ] if (enrolled or lsn.is_free_preview) else [],
                    }
                    for lsn in sorted(lessons_by_ch.get(ch.id, []),
                                      key=lambda x: (x.position, x.id))
                ],
            }
            for ch in chapters
        ],
    }


# ============================================================ ENROLLMENTS (user-side)

@router.get("/me/enrollments", response_model=list[EnrollmentOut])
def list_my_enrollments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (db.query(Enrollment)
              .filter(Enrollment.user_id == user.id,
                      Enrollment.revoked_at.is_(None),
                      Enrollment.tenant_id == get_current_tenant_id())
              .order_by(Enrollment.last_accessed_at.desc().nullslast(),
                        Enrollment.enrolled_at.desc())
              .all())


@router.post("/courses/{slug}/enroll", response_model=EnrollmentOut, status_code=201)
def self_enroll_free_course(
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Free-course self-enrollment. Paid courses go through the
    payments flow + admin grant — this endpoint refuses those."""
    c = _live_course_scope(db).filter(Course.slug == slug).first()
    if not c:
        raise NotFoundError("Course not found")
    if c.enrollment_type != "free":
        raise ValidationError(
            "This course is not free. Complete purchase to enrol."
        )
    existing = _active_enrollment(db, user, c.id)
    if existing:
        return existing
    e = Enrollment(
        tenant_id=get_current_tenant_id(),
        user_id=user.id, course_id=c.id, source="free",
    )
    db.add(e); db.commit(); db.refresh(e)
    audit_log(db, user.id, "enrollment.self_enrolled",
              {"id": e.id, "course_id": c.id, "slug": c.slug})
    return e


# ============================================================ LESSON PROGRESS

@router.get("/enrollments/{enrollment_id}/progress",
            response_model=list[LessonProgressOut])
def list_progress(
    enrollment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    e = db.get(Enrollment, enrollment_id)
    if not e or e.user_id != user.id:
        raise NotFoundError("Enrollment not found")
    return list(db.query(LessonProgress).filter(
        LessonProgress.enrollment_id == enrollment_id,
    ).all())


@router.put("/enrollments/{enrollment_id}/progress/{lesson_id}",
            response_model=LessonProgressOut)
def update_progress(
    enrollment_id: int,
    lesson_id: int,
    payload: LessonProgressUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Idempotent upsert of per-lesson progress for the calling user."""
    e = db.get(Enrollment, enrollment_id)
    if not e or e.user_id != user.id or e.revoked_at is not None:
        raise NotFoundError("Enrollment not found")

    lsn = db.get(Lesson, lesson_id)
    if not lsn or lsn.is_deleted:
        raise NotFoundError("Lesson not found")

    p = db.query(LessonProgress).filter(
        LessonProgress.enrollment_id == e.id,
        LessonProgress.lesson_id == lsn.id,
    ).first()
    now = datetime.now(timezone.utc)

    if p is None:
        p = LessonProgress(
            tenant_id=get_current_tenant_id(),
            enrollment_id=e.id, lesson_id=lsn.id,
            started_at=now,
        )
        db.add(p)

    if payload.last_position_seconds is not None:
        p.last_position_seconds = payload.last_position_seconds
    if payload.watch_time_seconds is not None:
        p.watch_time_seconds = payload.watch_time_seconds
    if payload.checklist_state is not None:
        p.checklist_state = payload.checklist_state
    if payload.mark_completed:
        if p.first_completed_at is None:
            p.first_completed_at = now
        p.completed_at = now

    e.last_accessed_at = now
    db.commit(); db.refresh(p)

    # Re-check enrollment completion (might tip over the threshold)
    recalculate_completion(db, e)
    db.commit()
    return p


# ============================================================ ANNOUNCEMENTS (public-read)

@router.get("/courses/{slug}/announcements",
            response_model=list[CourseAnnouncementOut])
def list_course_announcements_public(
    slug: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    c = _live_course_scope(db).filter(Course.slug == slug).first()
    if not c:
        raise NotFoundError("Course not found")
    if not _active_enrollment(db, user, c.id):
        # Announcements are enrolled-students-only
        return []
    return (db.query(CourseAnnouncement)
              .filter(CourseAnnouncement.course_id == c.id)
              .order_by(CourseAnnouncement.is_pinned.desc(),
                        CourseAnnouncement.posted_at.desc())
              .all())


# ============================================================ LESSON NOTES (user-owned)

@router.get("/lessons/{lesson_id}/note", response_model=LessonNoteOut | None)
def get_my_note(
    lesson_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (db.query(LessonNote)
              .filter(LessonNote.user_id == user.id,
                      LessonNote.lesson_id == lesson_id)
              .first())


@router.put("/lessons/{lesson_id}/note", response_model=LessonNoteOut | None)
def upsert_my_note(
    lesson_id: int,
    payload: LessonNoteUpsertIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Empty body deletes (idempotent). Non-empty creates or updates."""
    n = (db.query(LessonNote)
           .filter(LessonNote.user_id == user.id,
                   LessonNote.lesson_id == lesson_id)
           .first())
    if not payload.body.strip():
        if n:
            db.delete(n); db.commit()
        return None
    if n is None:
        n = LessonNote(
            tenant_id=get_current_tenant_id(),
            user_id=user.id, lesson_id=lesson_id,
            body=payload.body,
        )
        db.add(n)
    else:
        n.body = payload.body
    db.commit(); db.refresh(n)
    return n


# ============================================================ COURSE REVIEWS

@router.get("/courses/{slug}/reviews", response_model=list[CourseReviewOut])
def list_course_reviews(slug: str, db: Session = Depends(get_db)):
    c = _live_course_scope(db).filter(Course.slug == slug).first()
    if not c:
        raise NotFoundError("Course not found")
    return (db.query(CourseReview)
              .filter(CourseReview.course_id == c.id,
                      CourseReview.is_published.is_(True))
              .order_by(CourseReview.created_at.desc())
              .all())


@router.put("/enrollments/{enrollment_id}/review", response_model=CourseReviewOut)
def upsert_course_review(
    enrollment_id: int,
    payload: CourseReviewUpsertIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    e = db.get(Enrollment, enrollment_id)
    if not e or e.user_id != user.id or e.revoked_at is not None:
        raise NotFoundError("Enrollment not found")
    r = db.query(CourseReview).filter(CourseReview.enrollment_id == e.id).first()
    if r is None:
        r = CourseReview(
            tenant_id=get_current_tenant_id(),
            course_id=e.course_id, enrollment_id=e.id, user_id=user.id,
            stars=payload.stars, body=payload.body,
        )
        db.add(r)
    else:
        r.stars = payload.stars
        r.body = payload.body
    db.commit(); db.refresh(r)
    return r


# ============================================================ QUIZ ATTEMPTS

@router.get("/quizzes/{lesson_id}/questions")
def list_public_quiz_questions(
    lesson_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List quiz questions for a lesson, with options nested inline so
    the player UI can render choice-question UIs without N+1 fetches.

    ``is_correct`` is REDACTED on options before submit (cheat-prevention).
    After submit, the player calls list_my_attempts which reveals the
    correct answers + per-question feedback.

    Requires active enrollment in the lesson's course.
    """
    lsn = db.get(Lesson, lesson_id)
    if not lsn or lsn.is_deleted:
        raise NotFoundError("Lesson not found")
    ch = db.get(Chapter, lsn.chapter_id)
    if not _active_enrollment(db, user, ch.course_id):
        raise SubscriptionRequiredError()
    quiz = db.query(LmsQuiz).filter(LmsQuiz.lesson_id == lsn.id).first()
    if not quiz:
        return []
    questions = list(db.query(LmsQuizQuestion)
                       .filter(LmsQuizQuestion.quiz_id == quiz.id)
                       .order_by(LmsQuizQuestion.position).all())
    if not questions:
        return []
    options_by_q: dict[int, list[LmsQuizQuestionOption]] = {}
    for o in db.query(LmsQuizQuestionOption).filter(
        LmsQuizQuestionOption.question_id.in_([q.id for q in questions])
    ).order_by(LmsQuizQuestionOption.position).all():
        options_by_q.setdefault(o.question_id, []).append(o)
    return [
        {
            "id": q.id,
            "quiz_id": q.quiz_id,
            "position": q.position,
            "question_type": q.question_type,
            "question_text": q.question_text,
            "explanation": None,  # withheld until after submit
            "points": q.points,
            "accepted_answers": [],  # withheld until after submit
            "options": [
                {
                    "id": o.id,
                    "position": o.position,
                    "text": o.text,
                    # is_correct + reasoning withheld until submission
                }
                for o in options_by_q.get(q.id, [])
            ],
        }
        for q in questions
    ]


@router.post("/quizzes/{lesson_id}/attempts", response_model=QuizAttemptOut,
             status_code=201)
def submit_quiz_attempt(
    lesson_id: int,
    payload: QuizAttemptSubmitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit a quiz attempt. Creates a new attempt row, scores it
    against the question set, and stamps pass/fail."""
    lsn = db.get(Lesson, lesson_id)
    if not lsn or lsn.is_deleted:
        raise NotFoundError("Lesson not found")
    ch = db.get(Chapter, lsn.chapter_id)
    e = _active_enrollment(db, user, ch.course_id)
    if not e:
        raise SubscriptionRequiredError()
    quiz = db.query(LmsQuiz).filter(LmsQuiz.lesson_id == lsn.id).first()
    if not quiz:
        raise NotFoundError("Quiz not configured for this lesson")
    # Check attempt cap
    if quiz.attempts_allowed is not None:
        used = db.query(LmsQuizAttempt).filter(
            LmsQuizAttempt.enrollment_id == e.id,
            LmsQuizAttempt.quiz_id == quiz.id,
        ).count()
        if used >= quiz.attempts_allowed:
            raise ConflictError(
                f"Attempt limit reached ({quiz.attempts_allowed})."
            )

    now = datetime.now(timezone.utc)
    a = LmsQuizAttempt(
        tenant_id=get_current_tenant_id(),
        enrollment_id=e.id, quiz_id=quiz.id,
        attempt_number=next_attempt_number(db, e.id, quiz.id),
        started_at=now, submitted_at=now,
    )
    db.add(a); db.flush()  # need attempt.id for answer rows

    answers_dicts: list[dict[str, Any]] = [a.model_dump() for a in payload.answers]
    score, max_pts, pct, passed = score_attempt(db, a, answers_dicts)
    a.score_points = score
    a.max_points = max_pts
    a.percent = pct
    a.passed = passed
    db.commit(); db.refresh(a)

    # Quiz passed → mark lesson complete (a quiz being "completed" =
    # at least one passing attempt)
    if passed:
        p = db.query(LessonProgress).filter(
            LessonProgress.enrollment_id == e.id,
            LessonProgress.lesson_id == lsn.id,
        ).first()
        if p is None:
            p = LessonProgress(
                tenant_id=get_current_tenant_id(),
                enrollment_id=e.id, lesson_id=lsn.id,
                started_at=now,
            )
            db.add(p)
        if p.first_completed_at is None:
            p.first_completed_at = now
        p.completed_at = now
        recalculate_completion(db, e)
        db.commit()

    audit_log(db, user.id, "quiz.attempt_submitted",
              {"attempt_id": a.id, "quiz_id": quiz.id, "passed": passed,
               "percent": pct})
    return a


@router.get("/quizzes/{lesson_id}/attempts", response_model=list[QuizAttemptOut])
def list_my_attempts(
    lesson_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My past attempts on this lesson's quiz."""
    lsn = db.get(Lesson, lesson_id)
    if not lsn or lsn.is_deleted:
        raise NotFoundError("Lesson not found")
    ch = db.get(Chapter, lsn.chapter_id)
    e = _active_enrollment(db, user, ch.course_id)
    if not e:
        return []
    quiz = db.query(LmsQuiz).filter(LmsQuiz.lesson_id == lsn.id).first()
    if not quiz:
        return []
    return (db.query(LmsQuizAttempt)
              .filter(LmsQuizAttempt.enrollment_id == e.id,
                      LmsQuizAttempt.quiz_id == quiz.id)
              .order_by(LmsQuizAttempt.attempt_number.desc())
              .all())
