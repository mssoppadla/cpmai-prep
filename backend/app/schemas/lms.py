"""Pydantic schemas for the LMS API.

Three flavours per resource (where it makes sense):
  * ``*Out``         — full admin payload (everything the admin can edit)
  * ``*PublicOut``   — trimmed, end-user payload (drafts/soft-deleted hidden)
  * ``*CreateIn`` / ``*UpdateIn`` — request bodies (partial on update)

Pydantic-side enum validation uses Literal types so we don't depend on
SQL enums (forward-flex per the same pattern as content_pages).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Pydantic-side enums — mirror the Python tuples in app/models/lms.py
EnrollmentType = Literal["free", "paid", "subscription_bundle"]
Difficulty     = Literal["beginner", "intermediate", "advanced"]
LessonType     = Literal["video", "text", "quiz", "checklist", "live", "assignment"]
VideoProvider  = Literal["r2", "youtube", "vimeo", "stream"]
FileCategory   = Literal["assignment", "reference", "starter_code", "solution"]
EnrollmentSource = Literal["purchased", "admin_grant", "subscription", "free"]
QuestionType   = Literal["single_choice", "multi_choice", "true_false", "short_answer"]

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


# ============================================================ Course

class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    slug: str
    title: str
    subtitle: Optional[str]
    description: Optional[str]
    cover_image_url: Optional[str]
    base_price_paise: int
    currency: str
    plan_id: Optional[int]
    enrollment_type: EnrollmentType
    difficulty: Difficulty
    language: str
    estimated_hours: Optional[int]
    learning_outcomes: list[str]
    prerequisites_text: Optional[str]
    target_audience: Optional[str]
    completion_threshold_percent: int
    lead_instructor_id: Optional[int]
    discussion_url: Optional[str] = None
    display_order: int
    is_published: bool
    is_deleted: bool
    deleted_at: Optional[datetime]
    deleted_by: Optional[int]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime


class CoursePublicOut(BaseModel):
    """Public catalog payload — strips admin-only fields."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    title: str
    subtitle: Optional[str]
    description: Optional[str]
    cover_image_url: Optional[str]
    base_price_paise: int
    currency: str
    enrollment_type: EnrollmentType
    difficulty: Difficulty
    language: str
    estimated_hours: Optional[int]
    learning_outcomes: list[str]
    prerequisites_text: Optional[str]
    target_audience: Optional[str]
    completion_threshold_percent: int
    lead_instructor_id: Optional[int]
    discussion_url: Optional[str] = None
    display_order: int


class CourseCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=SLUG_PATTERN)
    title: str = Field(min_length=1, max_length=256)
    subtitle: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    base_price_paise: int = Field(default=0, ge=0)
    currency: str = Field(default="INR", max_length=3)
    plan_id: Optional[int] = None
    enrollment_type: EnrollmentType = "paid"
    difficulty: Difficulty = "beginner"
    language: str = Field(default="en", max_length=16)
    estimated_hours: Optional[int] = Field(default=None, ge=0)
    learning_outcomes: list[str] = Field(default_factory=list)
    prerequisites_text: Optional[str] = None
    target_audience: Optional[str] = None
    completion_threshold_percent: int = Field(default=100, ge=0, le=100)
    lead_instructor_id: Optional[int] = None
    discussion_url: Optional[str] = None
    display_order: int = Field(default=100, ge=0, le=10000)
    is_published: bool = False


class CourseUpdateIn(BaseModel):
    slug: Optional[str] = Field(default=None, min_length=1, max_length=128, pattern=SLUG_PATTERN)
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    subtitle: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    base_price_paise: Optional[int] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=3)
    plan_id: Optional[int] = None
    enrollment_type: Optional[EnrollmentType] = None
    difficulty: Optional[Difficulty] = None
    language: Optional[str] = Field(default=None, max_length=16)
    estimated_hours: Optional[int] = Field(default=None, ge=0)
    learning_outcomes: Optional[list[str]] = None
    prerequisites_text: Optional[str] = None
    target_audience: Optional[str] = None
    completion_threshold_percent: Optional[int] = Field(default=None, ge=0, le=100)
    lead_instructor_id: Optional[int] = None
    discussion_url: Optional[str] = None
    display_order: Optional[int] = Field(default=None, ge=0, le=10000)
    is_published: Optional[bool] = None


# ============================================================ Chapter

class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    course_id: int
    title: str
    description: Optional[str]
    position: int
    is_mandatory: bool
    is_published: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class ChapterCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = None
    position: int = Field(default=0, ge=0)
    is_mandatory: bool = True
    is_published: bool = True


class ChapterUpdateIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=0)
    is_mandatory: Optional[bool] = None
    is_published: Optional[bool] = None


# ============================================================ Lesson

class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    chapter_id: int
    lesson_type: LessonType
    title: str
    subtitle: Optional[str]
    position: int
    is_mandatory: bool
    video_url: Optional[str]
    video_provider: Optional[VideoProvider]
    video_object_key: Optional[str]
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    captions_url: Optional[str]
    body_blocks: list[dict[str, Any]]
    checklist_items: list[dict[str, Any]]
    discussion_url: Optional[str]
    instructor_id: Optional[int]
    quiz_pass_threshold_percent: int
    quiz_attempts_allowed: Optional[int]
    is_free_preview: bool
    is_published: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class LessonPublicOut(BaseModel):
    """Stripped for non-enrolled users — sensitive fields like
    ``video_object_key`` aren't exposed (the signed-URL endpoint
    in PR #9 handles that). Body content is included only for
    free-preview lessons; for paid lessons the endpoint masks it."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    chapter_id: int
    lesson_type: LessonType
    title: str
    subtitle: Optional[str]
    position: int
    is_mandatory: bool
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    discussion_url: Optional[str]
    instructor_id: Optional[int]
    is_free_preview: bool
    # Conditional fields — endpoint sets these to None for non-enrolled users
    video_url: Optional[str] = None
    body_blocks: list[dict[str, Any]] = Field(default_factory=list)


class LessonCreateIn(BaseModel):
    lesson_type: LessonType
    title: str = Field(min_length=1, max_length=256)
    subtitle: Optional[str] = Field(default=None, max_length=256)
    position: int = Field(default=0, ge=0)
    is_mandatory: bool = True
    video_url: Optional[str] = None
    video_provider: Optional[VideoProvider] = None
    video_object_key: Optional[str] = None
    duration_seconds: Optional[int] = Field(default=None, ge=0)
    thumbnail_url: Optional[str] = None
    captions_url: Optional[str] = None
    body_blocks: list[dict[str, Any]] = Field(default_factory=list)
    checklist_items: list[dict[str, Any]] = Field(default_factory=list)
    discussion_url: Optional[str] = None
    instructor_id: Optional[int] = None
    quiz_pass_threshold_percent: int = Field(default=70, ge=0, le=100)
    quiz_attempts_allowed: Optional[int] = Field(default=None, ge=1)
    is_free_preview: bool = False
    is_published: bool = True


class LessonUpdateIn(BaseModel):
    lesson_type: Optional[LessonType] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    subtitle: Optional[str] = Field(default=None, max_length=256)
    position: Optional[int] = Field(default=None, ge=0)
    is_mandatory: Optional[bool] = None
    video_url: Optional[str] = None
    video_provider: Optional[VideoProvider] = None
    video_object_key: Optional[str] = None
    duration_seconds: Optional[int] = Field(default=None, ge=0)
    thumbnail_url: Optional[str] = None
    captions_url: Optional[str] = None
    body_blocks: Optional[list[dict[str, Any]]] = None
    checklist_items: Optional[list[dict[str, Any]]] = None
    discussion_url: Optional[str] = None
    instructor_id: Optional[int] = None
    quiz_pass_threshold_percent: Optional[int] = Field(default=None, ge=0, le=100)
    quiz_attempts_allowed: Optional[int] = Field(default=None, ge=1)
    is_free_preview: Optional[bool] = None
    is_published: Optional[bool] = None


# ============================================================ Lesson Files

class LessonFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    lesson_id: int
    filename: str
    file_url: str
    file_object_key: Optional[str]
    file_size_bytes: Optional[int]
    mime_type: Optional[str]
    description: Optional[str]
    file_category: FileCategory
    is_required: bool
    position: int
    uploaded_by_id: Optional[int]
    created_at: datetime


class LessonFileCreateIn(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    file_url: str = Field(min_length=1)
    file_object_key: Optional[str] = None
    file_size_bytes: Optional[int] = Field(default=None, ge=0)
    mime_type: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = None
    file_category: FileCategory = "reference"
    is_required: bool = False
    position: int = Field(default=0, ge=0)


# ============================================================ Enrollment

class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    user_id: int
    course_id: int
    source: EnrollmentSource
    enrolled_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    completed_at: Optional[datetime]
    last_accessed_at: Optional[datetime]
    granted_by_id: Optional[int]
    grant_reason: Optional[str]
    payment_id: Optional[int]
    offer_code_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    # Display extras — populated by the learner-facing list endpoint so the
    # dashboard "My courses" cards can render a progress bar + link without
    # an extra round-trip. Optional so admin/ORM serialization stays valid.
    course_title: Optional[str] = None
    course_slug: Optional[str] = None
    lessons_completed: Optional[int] = None
    lessons_total: Optional[int] = None
    progress_percent: Optional[int] = None


class EnrollmentGrantIn(BaseModel):
    """Admin grants a free enrollment to a specific user."""
    user_id: int
    expires_at: Optional[datetime] = None
    grant_reason: str = Field(min_length=1, max_length=1000)


# ============================================================ Lesson Progress

class LessonProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enrollment_id: int
    lesson_id: int
    started_at: Optional[datetime]
    first_completed_at: Optional[datetime]
    completed_at: Optional[datetime]
    last_position_seconds: int
    watch_time_seconds: int
    checklist_state: dict[str, Any]


class LessonProgressUpdateIn(BaseModel):
    """Student-side update — caller is the authenticated user.
    Endpoint validates enrollment ownership."""
    last_position_seconds: Optional[int] = Field(default=None, ge=0)
    watch_time_seconds: Optional[int] = Field(default=None, ge=0)
    checklist_state: Optional[dict[str, Any]] = None
    mark_completed: Optional[bool] = None  # explicit one-shot toggle


# ============================================================ Course Category

class CourseCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    description: Optional[str]
    display_order: int


class CourseCategoryCreateIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    description: Optional[str] = None
    display_order: int = Field(default=100, ge=0)


class CourseCategoryUpdateIn(BaseModel):
    slug: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=SLUG_PATTERN)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    display_order: Optional[int] = Field(default=None, ge=0)


# ============================================================ Course Announcement

class CourseAnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    title: str
    body: str
    posted_by: Optional[int]
    posted_at: datetime
    is_pinned: bool


class CourseAnnouncementCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1)
    is_pinned: bool = False


# ============================================================ Lesson Note (student)

class LessonNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lesson_id: int
    body: str
    created_at: datetime
    updated_at: datetime


class LessonNoteUpsertIn(BaseModel):
    body: str = Field(min_length=0, max_length=20000)  # empty body deletes


# ============================================================ Course Review (student)

class CourseReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    user_id: int
    stars: int
    body: Optional[str]
    is_published: bool
    created_at: datetime
    updated_at: datetime


class CourseReviewUpsertIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    body: Optional[str] = Field(default=None, max_length=4000)


# ============================================================ Quiz

class QuizOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int
    text: str
    is_correct: bool
    reasoning: Optional[str]


class QuizQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    quiz_id: int
    position: int
    question_type: QuestionType
    question_text: str
    explanation: Optional[str]
    points: int
    accepted_answers: list[str]


class QuizOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lesson_id: int
    pass_threshold_percent: int
    attempts_allowed: Optional[int]
    time_limit_seconds: Optional[int]
    shuffle_questions: bool
    show_correct_answers: bool


class QuizConfigUpsertIn(BaseModel):
    """Idempotent upsert of quiz config for a lesson."""
    pass_threshold_percent: int = Field(default=70, ge=0, le=100)
    attempts_allowed: Optional[int] = Field(default=None, ge=1)
    time_limit_seconds: Optional[int] = Field(default=None, ge=1)
    shuffle_questions: bool = False
    show_correct_answers: bool = True


class QuizQuestionCreateIn(BaseModel):
    question_type: QuestionType
    question_text: str = Field(min_length=1)
    explanation: Optional[str] = None
    points: int = Field(default=1, ge=0)
    position: int = Field(default=0, ge=0)
    accepted_answers: list[str] = Field(default_factory=list)


class QuizQuestionUpdateIn(BaseModel):
    question_type: Optional[QuestionType] = None
    question_text: Optional[str] = Field(default=None, min_length=1)
    explanation: Optional[str] = None
    points: Optional[int] = Field(default=None, ge=0)
    position: Optional[int] = Field(default=None, ge=0)
    accepted_answers: Optional[list[str]] = None


class QuizOptionCreateIn(BaseModel):
    text: str = Field(min_length=1)
    is_correct: bool = False
    reasoning: Optional[str] = None
    position: int = Field(default=0, ge=0)


class QuizOptionUpdateIn(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1)
    is_correct: Optional[bool] = None
    reasoning: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=0)


# Quiz attempts (student-facing)

class QuizAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    enrollment_id: int
    quiz_id: int
    attempt_number: int
    started_at: datetime
    submitted_at: Optional[datetime]
    score_points: int
    max_points: int
    percent: int
    passed: bool


class QuizAttemptAnswerIn(BaseModel):
    """One answer in a submit payload."""
    question_id: int
    selected_option_ids: list[int] = Field(default_factory=list)
    short_answer_text: Optional[str] = None


class QuizAttemptSubmitIn(BaseModel):
    """Submit payload — array of per-question answers."""
    answers: list[QuizAttemptAnswerIn]


class QuizAttemptAnswerOut(BaseModel):
    """Per-question result shown after submit."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    question_id: int
    selected_option_ids: list[int]
    short_answer_text: Optional[str]
    points_awarded: int
