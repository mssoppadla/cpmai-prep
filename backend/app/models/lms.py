"""LMS ORM models — 16 tables for courses, chapters, lessons,
enrollments, progress, categories, announcements, notes, reviews,
and the fresh quiz schema (quizzes + questions + options + attempts
+ answers).

All tables carry ``tenant_id`` per contract I-1. Soft-delete pattern
follows PR #6 (operator preference): courses + chapters + lessons
use a partial unique index pattern (constraint applies only to
non-deleted rows) so admin can reuse a slug after delete. Hard-delete
on lesson_files because they're easy to re-upload.

Models intentionally light on relationship() definitions — endpoints
prefer explicit JOINs for clarity over ORM-traversal magic. We
declare FKs on Column() so cascade behaviour is enforced by the DB,
not the ORM layer.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer,
    JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


# Allowed values, mirrored from the migration. Kept in sync as module
# constants so endpoint code can validate without hitting the DB.
COURSE_ENROLLMENT_TYPES = ("free", "paid", "subscription_bundle")
COURSE_DIFFICULTIES     = ("beginner", "intermediate", "advanced")
LESSON_TYPES            = ("video", "text", "quiz", "checklist", "live", "assignment")
LESSON_VIDEO_PROVIDERS  = ("r2", "youtube", "vimeo", "stream")
LESSON_FILE_CATEGORIES  = ("assignment", "reference", "starter_code", "solution")
ENROLLMENT_SOURCES      = ("purchased", "admin_grant", "subscription", "free")
QUIZ_QUESTION_TYPES     = ("single_choice", "multi_choice", "true_false", "short_answer")


# ===================================================================
# 1. courses
# ===================================================================

class Course(Base):
    __tablename__ = "courses"

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1, index=True)
    slug      = Column(String(128), nullable=False)
    title     = Column(String(256), nullable=False)
    subtitle  = Column(String(256))
    description = Column(Text)
    cover_image_url = Column(Text)

    base_price_paise = Column(BigInteger, nullable=False, default=0)
    currency         = Column(String(3),  nullable=False, default="INR")
    plan_id          = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"))
    enrollment_type  = Column(String(32), nullable=False, default="paid")

    difficulty       = Column(String(32), nullable=False, default="beginner")
    language         = Column(String(16), nullable=False, default="en")
    estimated_hours  = Column(Integer)
    learning_outcomes = Column(JSON, nullable=False, default=list)
    prerequisites_text = Column(Text)
    target_audience   = Column(Text)
    completion_threshold_percent = Column(Integer, nullable=False, default=100)

    lead_instructor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    # Course-level default discussion URL (Discord channel, forum,
    # etc.). Inherited by every lesson UNLESS the lesson sets its own
    # discussion_url. Computed cascade lives at the API edge in
    # ``lms_public.get_public_course``.
    discussion_url     = Column(Text, nullable=True)
    display_order      = Column(Integer, nullable=False, default=100)

    is_published = Column(Boolean, nullable=False, default=False)
    is_deleted   = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at   = Column(DateTime(timezone=True))
    deleted_by   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_by   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 2. chapters
# ===================================================================

class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("course_id", "position",
                         name="uq_chapters_course_position"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    title     = Column(String(256), nullable=False)
    description = Column(Text)
    position  = Column(Integer, nullable=False, default=0)
    is_mandatory = Column(Boolean, nullable=False, default=True)
    is_published = Column(Boolean, nullable=False, default=True)

    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 3. lessons
# ===================================================================

class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("chapter_id", "position",
                         name="uq_lessons_chapter_position"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    lesson_type = Column(String(32), nullable=False)
    title       = Column(String(256), nullable=False)
    subtitle    = Column(String(256))
    position    = Column(Integer, nullable=False, default=0)
    is_mandatory = Column(Boolean, nullable=False, default=True)

    # Video-specific
    video_url        = Column(Text)
    video_provider   = Column(String(16))
    video_object_key = Column(Text)
    duration_seconds = Column(Integer)
    thumbnail_url    = Column(Text)
    captions_url     = Column(Text)

    body_blocks     = Column(JSON, nullable=False, default=list)
    checklist_items = Column(JSON, nullable=False, default=list)
    discussion_url  = Column(Text)
    instructor_id   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    quiz_pass_threshold_percent = Column(Integer, nullable=False, default=70)
    quiz_attempts_allowed       = Column(Integer)

    is_free_preview = Column(Boolean, nullable=False, default=False)
    is_published    = Column(Boolean, nullable=False, default=True)

    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 4. lesson_files
# ===================================================================

class LessonFile(Base):
    __tablename__ = "lesson_files"

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    lesson_id = Column(Integer, ForeignKey("lessons.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    filename  = Column(String(256), nullable=False)
    file_url  = Column(Text, nullable=False)
    file_object_key = Column(Text)
    file_size_bytes = Column(BigInteger)
    mime_type   = Column(String(128))
    description = Column(Text)
    file_category = Column(String(32), nullable=False, default="reference")
    is_required = Column(Boolean, nullable=False, default=False)
    position    = Column(Integer, nullable=False, default=0)
    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 5. enrollments
# ===================================================================

class Enrollment(Base):
    __tablename__ = "enrollments"

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    user_id   = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    source = Column(String(32), nullable=False)
    enrolled_at = Column(DateTime(timezone=True),
                         server_default=func.now(), nullable=False)
    expires_at  = Column(DateTime(timezone=True))
    revoked_at  = Column(DateTime(timezone=True))
    completed_at     = Column(DateTime(timezone=True))
    last_accessed_at = Column(DateTime(timezone=True))
    granted_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    grant_reason  = Column(Text)
    payment_id    = Column(Integer, ForeignKey("payments.id",     ondelete="SET NULL"))
    offer_code_id = Column(Integer, ForeignKey("offer_codes.id",  ondelete="SET NULL"))

    # "Listen as podcast" resume pointer — which lesson the learner was on
    # and how far into it (seconds), tracked separately from per-lesson
    # video position so audio and video resume don't clobber each other.
    # Plain nullable ints (no FK / no server_default) keep the migration
    # drift-clean; the app resolves a missing/deleted lesson gracefully.
    podcast_lesson_id        = Column(Integer)
    podcast_position_seconds = Column(Integer)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 6. lesson_progress
# ===================================================================

class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "lesson_id",
                         name="uq_lesson_progress_enrollment_lesson"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    lesson_id     = Column(Integer, ForeignKey("lessons.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    started_at         = Column(DateTime(timezone=True))
    first_completed_at = Column(DateTime(timezone=True))
    completed_at       = Column(DateTime(timezone=True))
    last_position_seconds = Column(Integer, nullable=False, default=0)
    watch_time_seconds    = Column(Integer, nullable=False, default=0)
    checklist_state = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 7. course_categories
# ===================================================================

class CourseCategory(Base):
    __tablename__ = "course_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug",
                         name="uq_course_categories_tenant_slug"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    slug = Column(String(64),  nullable=False)
    name = Column(String(128), nullable=False)
    description   = Column(Text)
    display_order = Column(Integer, nullable=False, default=100)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 8. course_category_links
# ===================================================================

class CourseCategoryLink(Base):
    __tablename__ = "course_category_links"
    __table_args__ = (
        UniqueConstraint("course_id", "category_id",
                         name="uq_course_category_links_course_category"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    course_id   = Column(Integer, ForeignKey("courses.id",            ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("course_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at  = Column(DateTime(timezone=True),
                         server_default=func.now(), nullable=False)


# ===================================================================
# 9. course_announcements
# ===================================================================

class CourseAnnouncement(Base):
    __tablename__ = "course_announcements"

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    title  = Column(String(256), nullable=False)
    body   = Column(Text, nullable=False)
    posted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    posted_at = Column(DateTime(timezone=True),
                       server_default=func.now(), nullable=False)
    is_pinned = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 10. lesson_notes
# ===================================================================

class LessonNote(Base):
    __tablename__ = "lesson_notes"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id",
                         name="uq_lesson_notes_user_lesson"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    user_id   = Column(Integer, ForeignKey("users.id",   ondelete="CASCADE"), nullable=False, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True)
    body = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 11. course_reviews
# ===================================================================

class CourseReview(Base):
    __tablename__ = "course_reviews"
    __table_args__ = (
        UniqueConstraint("enrollment_id", name="uq_course_reviews_enrollment"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    course_id     = Column(Integer, ForeignKey("courses.id",     ondelete="CASCADE"), nullable=False, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id       = Column(Integer, ForeignKey("users.id",        ondelete="CASCADE"), nullable=False)
    stars        = Column(Integer, nullable=False)
    body         = Column(Text)
    is_published = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 12. lms_quizzes
# ===================================================================

class LmsQuiz(Base):
    __tablename__ = "lms_quizzes"

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    lesson_id = Column(Integer, ForeignKey("lessons.id", ondelete="CASCADE"),
                       nullable=False, unique=True)
    pass_threshold_percent = Column(Integer, nullable=False, default=70)
    attempts_allowed       = Column(Integer)
    time_limit_seconds     = Column(Integer)
    shuffle_questions      = Column(Boolean, nullable=False, default=False)
    show_correct_answers   = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 13. lms_quiz_questions
# ===================================================================

class LmsQuizQuestion(Base):
    __tablename__ = "lms_quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position",
                         name="uq_lms_quiz_questions_quiz_position"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    quiz_id   = Column(Integer, ForeignKey("lms_quizzes.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    position  = Column(Integer, nullable=False, default=0)
    question_type = Column(String(32), nullable=False)
    question_text = Column(Text, nullable=False)
    explanation   = Column(Text)
    points        = Column(Integer, nullable=False, default=1)
    accepted_answers = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 14. lms_quiz_question_options
# ===================================================================

class LmsQuizQuestionOption(Base):
    __tablename__ = "lms_quiz_question_options"
    __table_args__ = (
        UniqueConstraint("question_id", "position",
                         name="uq_lms_quiz_options_question_position"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    question_id = Column(Integer, ForeignKey("lms_quiz_questions.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    position   = Column(Integer, nullable=False, default=0)
    text       = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)
    reasoning  = Column(Text)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)


# ===================================================================
# 15. lms_quiz_attempts
# ===================================================================

class LmsQuizAttempt(Base):
    __tablename__ = "lms_quiz_attempts"

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    quiz_id   = Column(Integer, ForeignKey("lms_quizzes.id",  ondelete="CASCADE"),
                       nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    started_at     = Column(DateTime(timezone=True),
                            server_default=func.now(), nullable=False)
    submitted_at   = Column(DateTime(timezone=True))
    score_points   = Column(Integer, nullable=False, default=0)
    max_points     = Column(Integer, nullable=False, default=0)
    percent        = Column(Integer, nullable=False, default=0)
    passed         = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)


# ===================================================================
# 16. lms_quiz_attempt_answers
# ===================================================================

class LmsQuizAttemptAnswer(Base):
    __tablename__ = "lms_quiz_attempt_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id",
                         name="uq_lms_quiz_attempt_answers_attempt_question"),
    )

    id        = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1)
    attempt_id  = Column(Integer, ForeignKey("lms_quiz_attempts.id",   ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("lms_quiz_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    selected_option_ids = Column(JSON, nullable=False, default=list)
    short_answer_text   = Column(Text)
    points_awarded      = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
