"""v6.4: LMS foundation — courses, chapters, lessons, files, enrollments,
progress, categories, announcements, notes, reviews, and quiz schema.

Adds 16 new tables in one transaction to support the LMS feature:

  Core hierarchy (6):
    courses, chapters, lessons, lesson_files, enrollments, lesson_progress
  Polish (5):
    course_categories, course_category_links, course_announcements,
    lesson_notes, course_reviews
  Quiz schema (5):
    lms_quizzes, lms_quiz_questions, lms_quiz_question_options,
    lms_quiz_attempts, lms_quiz_attempt_answers

Per Phase 1 contract:
  - I-1: every table carries tenant_id
  - M-1, M-2, M-3: additive only, downgrade NotImplementedError,
    single transaction (so a partial failure rolls everything back)

Slug uniqueness on ``courses`` uses a PARTIAL unique index that
excludes soft-deleted rows — lesson learned from PR #6 (cms slug
reuse after delete).

Revision ID kept short (``0027_lms_foundation`` = 19 chars) to fit
the Postgres ``alembic_version.version_num`` VARCHAR(32) limit
(lesson from PR #3).

Revision ID: 0027_lms_foundation
Revises: 0026_cp_slug_partial
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_lms_foundation"
down_revision = "0026_cp_slug_partial"
branch_labels = None
depends_on = None


# Reusable column factories so every table has the same tenant + timestamp shape.

def _tenant_fk() -> sa.Column:
    """tenant_id NOT NULL, defaults to 1 (CPMAI), FK to tenants with cascade."""
    return sa.Column(
        "tenant_id", sa.Integer,
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, server_default="1",
    )


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # =================================================================
    # 1. courses
    # =================================================================
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("slug",        sa.String(128), nullable=False),
        sa.Column("title",       sa.String(256), nullable=False),
        sa.Column("subtitle",    sa.String(256), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("cover_image_url", sa.Text, nullable=True),
        # Pricing
        sa.Column("base_price_paise", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("currency",         sa.String(3),  nullable=False, server_default="INR"),
        sa.Column("plan_id",          sa.Integer,    sa.ForeignKey("plans.id", ondelete="SET NULL"), nullable=True),
        # "free" | "paid" | "subscription_bundle"
        sa.Column("enrollment_type",  sa.String(32), nullable=False, server_default="paid"),
        # Marketing / categorisation
        sa.Column("difficulty",   sa.String(32), nullable=False, server_default="beginner"),
        sa.Column("language",     sa.String(16), nullable=False, server_default="en"),
        sa.Column("estimated_hours", sa.Integer, nullable=True),
        # JSONB for forward-flex (BlockNote may also live here later)
        sa.Column("learning_outcomes", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("prerequisites_text", sa.Text, nullable=True),
        sa.Column("target_audience",    sa.Text, nullable=True),
        # Completion rules
        sa.Column("completion_threshold_percent", sa.Integer, nullable=False, server_default="100"),
        # Public-facing instructor
        sa.Column("lead_instructor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        # Order in the catalog (lower = earlier)
        sa.Column("display_order", sa.Integer, nullable=False, server_default="100"),
        # Publication + soft-delete
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_deleted",   sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by",   sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by",   sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_ts_cols(),
    )
    op.create_index("ix_courses_tenant_pub", "courses",
                    ["tenant_id", "is_published", "display_order"])
    # Partial unique slug per tenant (lesson from PR #6).
    if is_postgres:
        op.execute(
            "CREATE UNIQUE INDEX uq_courses_tenant_slug_live "
            "ON courses (tenant_id, slug) WHERE is_deleted = FALSE"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX uq_courses_tenant_slug_live "
            "ON courses (tenant_id, slug) WHERE is_deleted = 0"
        )

    # =================================================================
    # 2. chapters (= "Week 1" / "Module 1" sections in the LMS UI)
    # =================================================================
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("course_id", sa.Integer,
                  sa.ForeignKey("courses.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("title",       sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("position",    sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_mandatory", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.true()),
        # Soft delete (matches courses pattern)
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("course_id", "position", name="uq_chapters_course_position"),
    )

    # =================================================================
    # 3. lessons
    # =================================================================
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("chapter_id", sa.Integer,
                  sa.ForeignKey("chapters.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # "video" | "text" | "quiz" | "checklist" | "live" | "assignment"
        # live + assignment are reserved for Phase 2 (no full impl yet).
        sa.Column("lesson_type", sa.String(32), nullable=False),
        sa.Column("title",       sa.String(256), nullable=False),
        sa.Column("subtitle",    sa.String(256), nullable=True),
        sa.Column("position",    sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_mandatory", sa.Boolean, nullable=False, server_default=sa.true()),
        # Video-specific
        sa.Column("video_url",       sa.Text, nullable=True),
        sa.Column("video_provider",  sa.String(16), nullable=True),  # r2 | youtube | vimeo | stream
        sa.Column("video_object_key", sa.Text, nullable=True),        # for R2 signed URLs
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("thumbnail_url",   sa.Text, nullable=True),
        sa.Column("captions_url",    sa.Text, nullable=True),
        # Text-lesson body (BlockNote blocks). Reuses the same JSON
        # shape as content_pages.blocks so the editor stack is shared.
        sa.Column("body_blocks", sa.JSON, nullable=False, server_default="[]"),
        # Checklist-lesson items
        sa.Column("checklist_items", sa.JSON, nullable=False, server_default="[]"),
        # Discussion link (e.g. Discord thread) for the "Ask Questions" tab
        sa.Column("discussion_url", sa.Text, nullable=True),
        # Per-lesson instructor override
        sa.Column("instructor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        # Quiz config (only meaningful for lesson_type='quiz' — see lms_quizzes for full schema)
        sa.Column("quiz_pass_threshold_percent", sa.Integer, nullable=False, server_default="70"),
        sa.Column("quiz_attempts_allowed", sa.Integer, nullable=True),  # NULL = unlimited
        # Free preview = visible without enrollment
        sa.Column("is_free_preview", sa.Boolean, nullable=False, server_default=sa.false()),
        # Publication
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.true()),
        # Soft delete
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_ts_cols(),
        sa.UniqueConstraint("chapter_id", "position", name="uq_lessons_chapter_position"),
    )

    # =================================================================
    # 4. lesson_files (downloadables attached to a lesson)
    # =================================================================
    op.create_table(
        "lesson_files",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("lesson_id", sa.Integer,
                  sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("filename",        sa.String(256), nullable=False),
        sa.Column("file_url",        sa.Text,        nullable=False),
        sa.Column("file_object_key", sa.Text,        nullable=True),   # for R2 signed URLs
        sa.Column("file_size_bytes", sa.BigInteger,  nullable=True),
        sa.Column("mime_type",       sa.String(128), nullable=True),
        sa.Column("description",     sa.Text,        nullable=True),
        # "assignment" | "reference" | "starter_code" | "solution"
        sa.Column("file_category",   sa.String(32),  nullable=False, server_default="reference"),
        sa.Column("is_required",     sa.Boolean,     nullable=False, server_default=sa.false()),
        sa.Column("position",        sa.Integer,     nullable=False, server_default="0"),
        sa.Column("uploaded_by_id",  sa.Integer,     sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_ts_cols(),
    )

    # =================================================================
    # 5. enrollments
    # =================================================================
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("course_id", sa.Integer,
                  sa.ForeignKey("courses.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # "purchased" | "admin_grant" | "subscription" | "free"
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at",  sa.DateTime(timezone=True), nullable=True),  # NULL = lifetime
        sa.Column("revoked_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at",  sa.DateTime(timezone=True), nullable=True),
        # Admin grant attribution
        sa.Column("granted_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("grant_reason",  sa.Text,    nullable=True),
        # Purchase attribution
        sa.Column("payment_id",    sa.Integer, sa.ForeignKey("payments.id",     ondelete="SET NULL"), nullable=True),
        sa.Column("offer_code_id", sa.Integer, sa.ForeignKey("offer_codes.id",  ondelete="SET NULL"), nullable=True),
        *_ts_cols(),
    )
    # One non-revoked enrollment per user per course (revoked rows are
    # kept for audit; new enrollment after revoke is allowed).
    if is_postgres:
        op.execute(
            "CREATE UNIQUE INDEX uq_enrollments_user_course_active "
            "ON enrollments (user_id, course_id) WHERE revoked_at IS NULL"
        )
    else:
        op.execute(
            "CREATE UNIQUE INDEX uq_enrollments_user_course_active "
            "ON enrollments (user_id, course_id) WHERE revoked_at IS NULL"
        )

    # =================================================================
    # 6. lesson_progress
    # =================================================================
    op.create_table(
        "lesson_progress",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("enrollment_id", sa.Integer,
                  sa.ForeignKey("enrollments.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("lesson_id", sa.Integer,
                  sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("started_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_completed_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_position_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("watch_time_seconds",    sa.Integer, nullable=False, server_default="0"),
        # For checklist lessons: { "0": true, "2": true } — index → checked
        sa.Column("checklist_state", sa.JSON, nullable=False, server_default="{}"),
        *_ts_cols(),
        sa.UniqueConstraint("enrollment_id", "lesson_id", name="uq_lesson_progress_enrollment_lesson"),
    )

    # =================================================================
    # 7. course_categories (per-tenant taxonomy)
    # =================================================================
    op.create_table(
        "course_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("slug",  sa.String(64),  nullable=False),
        sa.Column("name",  sa.String(128), nullable=False),
        sa.Column("description", sa.Text,  nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="100"),
        *_ts_cols(),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_course_categories_tenant_slug"),
    )

    # =================================================================
    # 8. course_category_links (M:N courses ↔ categories)
    # =================================================================
    op.create_table(
        "course_category_links",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("course_id",   sa.Integer, sa.ForeignKey("courses.id",            ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("course_categories.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("course_id", "category_id", name="uq_course_category_links_course_category"),
    )

    # =================================================================
    # 9. course_announcements
    # =================================================================
    op.create_table(
        "course_announcements",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title",     sa.String(256), nullable=False),
        sa.Column("body",      sa.Text,        nullable=False),
        sa.Column("posted_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_pinned", sa.Boolean, nullable=False, server_default=sa.false()),
        *_ts_cols(),
    )

    # =================================================================
    # 10. lesson_notes (student-owned)
    # =================================================================
    op.create_table(
        "lesson_notes",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("user_id",   sa.Integer, sa.ForeignKey("users.id",   ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("lesson_id", sa.Integer, sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("body", sa.Text, nullable=False),
        *_ts_cols(),
        sa.UniqueConstraint("user_id", "lesson_id", name="uq_lesson_notes_user_lesson"),
    )

    # =================================================================
    # 11. course_reviews
    # =================================================================
    op.create_table(
        "course_reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("course_id",     sa.Integer, sa.ForeignKey("courses.id",     ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("enrollment_id", sa.Integer, sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id",       sa.Integer, sa.ForeignKey("users.id",        ondelete="CASCADE"), nullable=False),
        sa.Column("stars", sa.Integer, nullable=False),
        sa.Column("body",  sa.Text,    nullable=True),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts_cols(),
        sa.UniqueConstraint("enrollment_id", name="uq_course_reviews_enrollment"),
    )

    # =================================================================
    # 12. lms_quizzes (config for a quiz-type lesson)
    # =================================================================
    op.create_table(
        "lms_quizzes",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("lesson_id", sa.Integer,
                  sa.ForeignKey("lessons.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("pass_threshold_percent", sa.Integer, nullable=False, server_default="70"),
        sa.Column("attempts_allowed",       sa.Integer, nullable=True),  # NULL = unlimited
        sa.Column("time_limit_seconds",     sa.Integer, nullable=True),
        sa.Column("shuffle_questions",      sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("show_correct_answers",   sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts_cols(),
    )

    # =================================================================
    # 13. lms_quiz_questions
    # =================================================================
    op.create_table(
        "lms_quiz_questions",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("quiz_id", sa.Integer, sa.ForeignKey("lms_quizzes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        # "single_choice" | "multi_choice" | "true_false" | "short_answer"
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("explanation",   sa.Text, nullable=True),
        sa.Column("points",        sa.Integer, nullable=False, server_default="1"),
        # For short_answer questions — comma-separated accepted answers
        sa.Column("accepted_answers", sa.JSON, nullable=False, server_default="[]"),
        *_ts_cols(),
        sa.UniqueConstraint("quiz_id", "position", name="uq_lms_quiz_questions_quiz_position"),
    )

    # =================================================================
    # 14. lms_quiz_question_options
    # =================================================================
    op.create_table(
        "lms_quiz_question_options",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("lms_quiz_questions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("position",   sa.Integer, nullable=False, server_default="0"),
        sa.Column("text",       sa.Text, nullable=False),
        sa.Column("is_correct", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reasoning",  sa.Text, nullable=True),  # explains why right/wrong
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("question_id", "position", name="uq_lms_quiz_options_question_position"),
    )

    # =================================================================
    # 15. lms_quiz_attempts (per-student attempt)
    # =================================================================
    op.create_table(
        "lms_quiz_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("enrollment_id", sa.Integer, sa.ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("quiz_id",       sa.Integer, sa.ForeignKey("lms_quizzes.id",  ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("started_at",     sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("submitted_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("score_points",   sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_points",     sa.Integer, nullable=False, server_default="0"),
        sa.Column("percent",        sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed",         sa.Boolean, nullable=False, server_default=sa.false()),
        *_ts_cols(),
    )

    # =================================================================
    # 16. lms_quiz_attempt_answers
    # =================================================================
    op.create_table(
        "lms_quiz_attempt_answers",
        sa.Column("id", sa.Integer, primary_key=True),
        _tenant_fk(),
        sa.Column("attempt_id",  sa.Integer, sa.ForeignKey("lms_quiz_attempts.id",   ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("lms_quiz_questions.id", ondelete="CASCADE"), nullable=False, index=True),
        # For choice questions: list of selected option_ids ([3] or [3, 5])
        # For short_answer: empty array
        sa.Column("selected_option_ids", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("short_answer_text",   sa.Text, nullable=True),
        sa.Column("points_awarded",      sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_lms_quiz_attempt_answers_attempt_question"),
    )


def downgrade() -> None:
    # Per contract M-2: downgrades are forward-only. Dropping all
    # 16 tables would silently destroy course content, student
    # enrollments, and quiz attempt history — never automate this.
    raise NotImplementedError(
        "0027_lms_foundation: downgrade is intentionally unimplemented. "
        "Removing the LMS schema would destroy operator-authored courses, "
        "student enrollment history, and quiz attempts. To reverse course "
        "on LMS, write a forward migration that exports + archives, then "
        "drops tables explicitly, and review the data-preservation "
        "contract first."
    )
