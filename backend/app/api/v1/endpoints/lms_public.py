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

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_current_user, get_db, get_optional_user
from app.core.media_tokens import protected_media_url
from app.core.exceptions import (
    ConflictError, NotFoundError, SubscriptionRequiredError,
    UnauthorizedError, ValidationError,
)
from app.core.tenant import get_current_tenant_id
from app.models.lms import (
    Chapter, Course, CourseAnnouncement, CourseCategory,
    CourseCategoryLink, CourseReview,
    Enrollment, Lesson, LessonFile, LessonNote, LessonProgress,
    LmsQuiz, LmsQuizAttempt, LmsQuizQuestion, LmsQuizQuestionOption,
)
from app.models.plan import PlanCourse
from app.models.subscription import Subscription
from app.models.user import User
from app.models.zoom import Recording, ZoomSession
from app.schemas.lms import (
    CourseAnnouncementOut, CoursePublicOut, CourseReviewOut,
    CourseReviewUpsertIn, EnrollmentOut, LessonFileOut, LessonNoteOut,
    LessonNoteUpsertIn, LessonProgressOut, LessonProgressUpdateIn,
    LessonPublicOut, QuizAttemptOut, QuizAttemptSubmitIn, QuizQuestionOut,
)
from app.schemas.zoom import (
    SignedRecordingPlaybackOut, ZoomSDKTokenOut, ZoomSessionPublicOut,
)
from app.services.lms.scoring import (
    course_progress, next_attempt_number, recalculate_completion,
    score_attempt,
)
from app.services.zoom_integration import (
    ZoomNotConfigured, zoom_client,
)


router = APIRouter()


# ============================================================ helpers

def _live_course_scope(db: Session):
    return db.query(Course).filter(
        Course.tenant_id == get_current_tenant_id(),
        Course.is_published.is_(True),
        Course.is_deleted.is_(False),
    )


def _has_active_subscription_bundle(
    db: Session, user_id: int, course_id: int,
) -> Subscription | None:
    """Returns the user's active Subscription whose plan bundles this
    course via plan_courses, if any. None if no such bundle exists.

    Used to grant 'implicit enrollment' for subscription customers
    without forcing the admin to manually enroll each user.
    """
    now = datetime.now(timezone.utc)
    return db.query(Subscription).join(
        PlanCourse, PlanCourse.plan_id == Subscription.plan_id,
    ).filter(
        Subscription.user_id == user_id,
        Subscription.revoked_at.is_(None),
        (Subscription.expires_at.is_(None)) | (Subscription.expires_at > now),
        Subscription.status == "active",
        PlanCourse.course_id == course_id,
        PlanCourse.tenant_id == get_current_tenant_id(),
    ).order_by(Subscription.id.desc()).first()


def _active_enrollment(db: Session, user: User | None, course_id: int) -> Enrollment | None:
    """Return the user's active enrollment for the course, creating one
    implicitly if they have a subscription whose plan bundles the course.

    "Implicit" enrollment = an Enrollment row with source='subscription',
    linked to their Subscription. This lets all the normal LMS flows
    (progress, notes, quiz attempts, completion calc) work without
    special-casing subscription users elsewhere in the codebase.
    """
    if user is None:
        return None
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.course_id == course_id,
        Enrollment.revoked_at.is_(None),
        Enrollment.tenant_id == get_current_tenant_id(),
    ).first()
    if enrollment is not None:
        return enrollment

    # No explicit enrollment — check if a subscription bundle covers this course
    sub = _has_active_subscription_bundle(db, user.id, course_id)
    if sub is None:
        return None

    # Implicit enrollment auto-create. Expires at the subscription's expiry
    # so it disappears cleanly when the sub lapses.
    enrollment = Enrollment(
        tenant_id=get_current_tenant_id(),
        user_id=user.id,
        course_id=course_id,
        source="subscription",
        expires_at=sub.expires_at,
        granted_by_id=None,
        grant_reason=f"Auto-enrolled via subscription #{sub.id} (plan {sub.plan_id})",
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    audit_log(db, user.id, "enrollment.auto_subscription",
              {"id": enrollment.id, "course_id": course_id,
               "subscription_id": sub.id, "plan_id": sub.plan_id})
    return enrollment


def _sign_block_media(blocks: list | None, viewer_id: int) -> list:
    """Rewrite ``/uploads/...`` URLs embedded in BlockNote body blocks
    (video / file / audio blocks) into signed, expiring URLs.

    ``protected_media_url`` is a no-op for images and external URLs, so
    applying it to every block that carries a ``props.url`` string is
    safe — only protected (non-image) uploads get a token appended.
    """
    if not blocks:
        return blocks or []
    signed: list = []
    for b in blocks:
        props = b.get("props") if isinstance(b, dict) else None
        if isinstance(props, dict) and isinstance(props.get("url"), str):
            signed.append({
                **b,
                "props": {**props,
                          "url": protected_media_url(props["url"], viewer_id)},
            })
        else:
            signed.append(b)
    return signed


def _redact_lesson(
    lsn: Lesson, is_enrolled: bool,
    course_discussion_url: str | None = None,
    viewer_id: int = 0,
) -> LessonPublicOut:
    """Build a public lesson payload. For non-enrolled users, lesson
    body / video_url are nulled unless the lesson is free_preview.

    For entitled viewers, protected media (uploaded video + non-image
    body-block files) is rewritten to signed, expiring ``/uploads/...?
    token=`` URLs via ``protected_media_url`` so a raw paid-media link
    can't be shared with non-payers. ``viewer_id`` is the user id (0 for
    anonymous free-preview) — carried in the token for audit.

    Computes the effective discussion_url cascade:
      lesson.discussion_url OR course.discussion_url OR None
    so the player's "Ask Questions" tab works from a single course-
    level default unless the operator specifically overrode the URL
    on this lesson.
    """
    show_body = is_enrolled or lsn.is_free_preview
    out = LessonPublicOut.model_validate(lsn)
    if not show_body:
        out.video_url = None
        out.body_blocks = []
    else:
        out.video_url = protected_media_url(out.video_url, viewer_id)
        out.body_blocks = _sign_block_media(out.body_blocks, viewer_id)
    if not out.discussion_url and course_discussion_url:
        out.discussion_url = course_discussion_url
    return out


# ============================================================ CATALOG

@router.get("/categories")
def list_public_categories(db: Session = Depends(get_db)):
    """Public categories — shown as filter pills on the /courses catalog."""
    return [
        {
            "id": c.id, "slug": c.slug, "name": c.name,
            "description": c.description, "display_order": c.display_order,
        }
        for c in db.query(CourseCategory).filter(
            CourseCategory.tenant_id == get_current_tenant_id()
        ).order_by(CourseCategory.display_order, CourseCategory.id).all()
    ]


@router.get("/courses")
def list_public_courses(
    db: Session = Depends(get_db),
    difficulty: str | None = Query(default=None),
    category: str | None = Query(default=None,
        description="Category slug — filters to courses tagged with this category"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Public catalog. Filters: difficulty, category. Each course's
    response includes its linked category slugs so cards can render
    badges without an extra round-trip per course."""
    q = _live_course_scope(db)
    if difficulty:
        q = q.filter(Course.difficulty == difficulty)
    if category:
        # Join through course_category_links + course_categories
        cat = db.query(CourseCategory).filter(
            CourseCategory.tenant_id == get_current_tenant_id(),
            CourseCategory.slug == category,
        ).first()
        if cat is None:
            return []
        q = q.join(
            CourseCategoryLink, CourseCategoryLink.course_id == Course.id,
        ).filter(CourseCategoryLink.category_id == cat.id)
    courses = (q.order_by(Course.display_order, Course.id)
                .offset(offset).limit(limit).all())

    # Load category links for all courses in one query (avoid N+1)
    course_ids = [c.id for c in courses]
    cat_map: dict[int, list[CourseCategory]] = {}
    if course_ids:
        rows = (db.query(CourseCategoryLink, CourseCategory)
                  .join(CourseCategory,
                        CourseCategory.id == CourseCategoryLink.category_id)
                  .filter(CourseCategoryLink.course_id.in_(course_ids))
                  .all())
        for link, cat in rows:
            cat_map.setdefault(link.course_id, []).append(cat)

    return [
        {
            **CoursePublicOut.model_validate(c).model_dump(mode="json"),
            "categories": [
                {"id": cc.id, "slug": cc.slug, "name": cc.name}
                for cc in cat_map.get(c.id, [])
            ],
        }
        for c in courses
    ]


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
    viewer_id = user.id if user else 0

    # Social-proof signal for the course detail hero: how many active
    # enrollments are on this course. We count rows from the canonical
    # enrollments table; expired / cancelled rows still flag interest
    # so we keep them in the count. Cheap aggregate so doesn't bloat
    # the request (single COUNT alongside the chapter fetch).
    enrollment_count = db.query(func.count(Enrollment.id)).filter(
        Enrollment.course_id == c.id,
        Enrollment.tenant_id == c.tenant_id,
    ).scalar() or 0

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
        "enrollment_count": enrollment_count,
        "chapters": [
            {
                "id": ch.id,
                "title": ch.title,
                "description": ch.description,
                "position": ch.position,
                "is_mandatory": ch.is_mandatory,
                "lessons": [
                    {
                        **_redact_lesson(lsn, enrolled, c.discussion_url,
                                         viewer_id).model_dump(),
                        "files": [
                            {**LessonFileOut.model_validate(f).model_dump(),
                             "file_url": protected_media_url(f.file_url, viewer_id)}
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
    """List the user's active enrollments — explicit + subscription-derived.

    For any course bundled in the user's active subscription that doesn't
    yet have an Enrollment row, auto-create one with source='subscription'
    so it appears immediately in the user's "My courses" list. This makes
    the bundle purchase experience feel one-click — the user doesn't have
    to discover each bundled course before it shows up.
    """
    now = datetime.now(timezone.utc)
    # 1. Find courses linked to the user's active subscription(s)
    subs = list(db.query(Subscription).filter(
        Subscription.user_id == user.id,
        Subscription.revoked_at.is_(None),
        (Subscription.expires_at.is_(None)) | (Subscription.expires_at > now),
        Subscription.status == "active",
    ).all())
    if subs:
        bundled = db.query(PlanCourse).filter(
            PlanCourse.plan_id.in_([s.plan_id for s in subs if s.plan_id]),
            PlanCourse.tenant_id == get_current_tenant_id(),
        ).all()
        already_enrolled = {
            e.course_id for e in db.query(Enrollment).filter(
                Enrollment.user_id == user.id,
                Enrollment.tenant_id == get_current_tenant_id(),
                Enrollment.revoked_at.is_(None),
            ).all()
        }
        # Pick the latest-expiring sub per course for the implicit enrollment.
        plan_to_sub = {s.plan_id: s for s in subs}
        for link in bundled:
            if link.course_id in already_enrolled:
                continue
            sub = plan_to_sub.get(link.plan_id)
            if not sub:
                continue
            # Course must still be live + non-deleted
            course = db.get(Course, link.course_id)
            if not course or course.is_deleted:
                continue
            db.add(Enrollment(
                tenant_id=get_current_tenant_id(),
                user_id=user.id,
                course_id=link.course_id,
                source="subscription",
                expires_at=sub.expires_at,
                grant_reason=f"Auto-enrolled via subscription #{sub.id} "
                             f"(plan {sub.plan_id})",
            ))
        db.commit()

    enrollments = (db.query(Enrollment)
              .filter(Enrollment.user_id == user.id,
                      Enrollment.revoked_at.is_(None),
                      Enrollment.tenant_id == get_current_tenant_id())
              .order_by(Enrollment.last_accessed_at.desc().nullslast(),
                        Enrollment.enrolled_at.desc())
              .all())

    # Course title/slug for the dashboard cards — one query, no N+1.
    course_ids = {e.course_id for e in enrollments}
    courses = (
        {c.id: c for c in db.query(Course).filter(Course.id.in_(course_ids)).all()}
        if course_ids else {}
    )
    out: list[dict] = []
    for e in enrollments:
        prog = course_progress(db, e)
        c = courses.get(e.course_id)
        out.append({
            **EnrollmentOut.model_validate(e).model_dump(),
            "course_title": c.title if c else None,
            "course_slug": c.slug if c else None,
            "lessons_completed": prog["lessons_completed"],
            "lessons_total": prog["lessons_total"],
            "progress_percent": prog["percent"],
        })
    return out


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


# ==========================================================================
# ZOOM SESSIONS — public access (subscription-gated)
# ==========================================================================
# A learner sees only sessions that:
#   1. Are NOT in draft state (admin hasn't published yet)
#   2. Are NOT soft-deleted
#   3. If course_id is set → they have an active enrollment on that course
#   4. If course_id is NULL (standalone) → they have ANY active subscription
#
# Joining a live session goes through /lms/sessions/{id}/sdk-token,
# which mints a 30-minute JWT bound to user + meeting_id. The session's
# raw zoom_join_url is NEVER returned to the frontend — that's what
# prevents URL-sharing with non-subscribers (a learner can't copy a
# join link out of the page, because there is no join link in the page).

def _user_can_view_session(
    db: Session, user: User, s: ZoomSession,
) -> bool:
    """Subscription gate for a single session."""
    if s.course_id is not None:
        # Course-linked → require enrollment on that course
        return _active_enrollment(db, user, s.course_id) is not None
    # Standalone session → require ANY active subscription.
    # NOTE: Subscription is a pre-multitenancy model and doesn't have a
    # `tenant_id` column (per `app/models/subscription.py`). Tenancy
    # scope is enforced upstream by the auth layer (user.tenant_id) plus
    # the surrounding zoom_session query (which is tenant-scoped). When
    # Subscription gains tenant_id in a future migration, add the filter
    # here for defense-in-depth.
    now = datetime.now(timezone.utc)
    return db.query(Subscription.id).filter(
        Subscription.user_id == user.id,
        Subscription.revoked_at.is_(None),
        (Subscription.expires_at.is_(None)) | (Subscription.expires_at > now),
        Subscription.status == "active",
    ).first() is not None


@router.get("/sessions", response_model=list[ZoomSessionPublicOut])
def list_my_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    course_id: int | None = Query(None,
        description="Optional: filter to a single course's sessions"),
    include_past: bool = Query(False,
        description="Default false = only upcoming + currently live"),
):
    """List sessions the user can see — published, non-deleted, and
    either course-enrolled or covered by an active subscription.

    Returns lightweight payload (no zoom_join_url). Frontend uses
    `id` + `status` to decide whether to render a 'Join live' button
    (status='live'), a 'Starts in N minutes' countdown (status='scheduled',
    scheduled_at in the future), or a 'Past' marker.
    """
    q = db.query(ZoomSession).filter(
        ZoomSession.tenant_id == get_current_tenant_id(),
        ZoomSession.is_deleted.is_(False),
        ZoomSession.status.in_(["scheduled", "live", "ended"]),
    )
    if course_id is not None:
        q = q.filter(ZoomSession.course_id == course_id)
    if not include_past:
        q = q.filter(ZoomSession.status.in_(["scheduled", "live"]))

    sessions = q.order_by(ZoomSession.scheduled_at.asc()).all()
    # Filter to ones this user can actually see — done in Python because
    # the access rule depends on course enrollment (a join) AND optional
    # subscription bundle (another join). Keeping it simple beats a
    # complex SQL OR.
    return [s for s in sessions if _user_can_view_session(db, user, s)]


@router.get("/sessions/{session_id}", response_model=ZoomSessionPublicOut)
def get_my_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = db.query(ZoomSession).filter(
        ZoomSession.id == session_id,
        ZoomSession.tenant_id == get_current_tenant_id(),
        ZoomSession.is_deleted.is_(False),
    ).first()
    if not s or s.status == "draft":
        raise NotFoundError("Session not found")
    if not _user_can_view_session(db, user, s):
        raise NotFoundError("Session not found")  # 404, not 403 — opaque
    return s


@router.post("/sessions/{session_id}/sdk-token",
             response_model=ZoomSDKTokenOut)
def get_session_sdk_token(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mint a Zoom Meeting SDK JWT for this user + session.

    Each token is bound to the user + meeting_id + 30-minute TTL.
    Forwarded URLs (sharing this token with a non-subscriber) fail
    because the receiver's frontend doesn't have a valid CPMAI auth
    token to even reach this endpoint.

    Audit-logged so admin can review any "weird join pattern" later.
    """
    s = db.query(ZoomSession).filter(
        ZoomSession.id == session_id,
        ZoomSession.tenant_id == get_current_tenant_id(),
        ZoomSession.is_deleted.is_(False),
    ).first()
    if not s:
        raise NotFoundError("Session not found")
    if not s.zoom_meeting_id:
        raise ValidationError(
            "This session hasn't been published to Zoom yet. "
            "Try again later — the admin is still setting it up."
        )
    if s.status not in ("scheduled", "live"):
        raise ValidationError(
            f"Session is not joinable in '{s.status}' state."
        )
    if not _user_can_view_session(db, user, s):
        raise NotFoundError("Session not found")
    try:
        signed = zoom_client.sign_sdk_token(
            meeting_number=s.zoom_meeting_id,
            user_name=user.name or user.email.split("@")[0],
            role=0,  # always participant; admin host gets a separate path
        )
    except ZoomNotConfigured as e:
        raise ValidationError(str(e)) from e
    audit_log(db, user.id, "zoom_session.sdk_token_issued",
              {"session_id": s.id, "meeting_id": s.zoom_meeting_id,
               "expires_at": signed.expires_at.isoformat()})
    return signed


@router.get("/sessions/{session_id}/recording",
            response_model=SignedRecordingPlaybackOut)
def get_session_recording(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mint a 1-hour signed playback URL for the latest recording of
    this session. Each call is audit-logged so anomalous playback
    patterns surface to ops.

    The current implementation returns the relative `/uploads/...`
    path directly because we're using local-disk storage; the frontend
    `absoluteUploadUrl` helper turns it into a cross-origin URL.
    When R2 lands (PR #9 follow-up), this swaps to a signed-URL flow
    and the `expires_at` field becomes a hard limit.
    """
    s = db.query(ZoomSession).filter(
        ZoomSession.id == session_id,
        ZoomSession.tenant_id == get_current_tenant_id(),
        ZoomSession.is_deleted.is_(False),
    ).first()
    if not s:
        raise NotFoundError("Session not found")
    if not _user_can_view_session(db, user, s):
        raise NotFoundError("Session not found")

    rec = (db.query(Recording)
             .filter(Recording.zoom_session_id == s.id,
                     Recording.tenant_id == get_current_tenant_id())
             .order_by(Recording.created_at.desc())
             .first())
    if not rec:
        raise NotFoundError("No recording available for this session yet")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    audit_log(db, user.id, "zoom_session.recording_playback_issued",
              {"session_id": s.id, "recording_id": rec.id,
               "expires_at": expires_at.isoformat()})

    return {
        # Token TTL matches the advertised 1-hour expiry so the signed
        # URL stops working exactly when ``expires_at`` says it does.
        "url": protected_media_url(rec.file_url, user.id, ttl_seconds=3600),
        "expires_at": expires_at,
        "duration_seconds": rec.duration_seconds,
    }
