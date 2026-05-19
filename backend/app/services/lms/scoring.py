"""Quiz scoring + course completion calculation.

Pure functions where possible; the DB-touching helpers take an
already-loaded ``Session`` so endpoints can call within their own
transaction boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lms import (
    Chapter, Course, Enrollment, Lesson, LessonProgress,
    LmsQuiz, LmsQuizAttempt, LmsQuizAttemptAnswer, LmsQuizQuestion,
    LmsQuizQuestionOption,
)


# ============================================================ Quiz scoring

def score_attempt(
    db: Session,
    attempt: LmsQuizAttempt,
    answers: list[dict],
) -> tuple[int, int, int, bool]:
    """Score an in-progress quiz attempt.

    ``answers`` is a list of ``{question_id, selected_option_ids, short_answer_text}``.

    Returns ``(score_points, max_points, percent, passed)``.

    Per-question scoring:
      - single_choice / true_false: 1 selected option, must be the correct one.
      - multi_choice: ALL correct options selected AND no incorrect ones selected.
      - short_answer: case-insensitive trimmed match against any of
        ``accepted_answers``.

    No partial credit for multi-choice in Phase 1; we can add it later
    if operators ask. Scoring writes per-question rows to
    ``lms_quiz_attempt_answers`` for review later.
    """
    quiz: LmsQuiz | None = db.get(LmsQuiz, attempt.quiz_id)
    if not quiz:
        return 0, 0, 0, False

    questions = list(db.execute(
        select(LmsQuizQuestion)
        .where(LmsQuizQuestion.quiz_id == quiz.id)
        .order_by(LmsQuizQuestion.position)
    ).scalars())

    answers_by_qid: dict[int, dict] = {
        a["question_id"]: a for a in answers
    }

    score_points = 0
    max_points = 0

    # Clear previous answers for this attempt (idempotent submit). This
    # only matters if score_attempt is called twice on the same attempt
    # — endpoints SHOULD only call once on submit, but defensively…
    db.query(LmsQuizAttemptAnswer).filter(
        LmsQuizAttemptAnswer.attempt_id == attempt.id
    ).delete(synchronize_session=False)

    for q in questions:
        max_points += q.points
        ans = answers_by_qid.get(q.id, {})
        is_correct = _grade_question(db, q, ans)
        awarded = q.points if is_correct else 0
        score_points += awarded
        db.add(LmsQuizAttemptAnswer(
            tenant_id=attempt.tenant_id,
            attempt_id=attempt.id,
            question_id=q.id,
            selected_option_ids=ans.get("selected_option_ids", []) or [],
            short_answer_text=ans.get("short_answer_text"),
            points_awarded=awarded,
        ))

    percent = round((score_points / max_points) * 100) if max_points else 0
    passed = percent >= (quiz.pass_threshold_percent or 70)
    return score_points, max_points, percent, passed


def _grade_question(
    db: Session,
    q: LmsQuizQuestion,
    answer: dict,
) -> bool:
    """Return True if ``answer`` is fully correct for ``q``."""
    qtype = q.question_type
    selected: list[int] = list(answer.get("selected_option_ids") or [])
    short_ans: str | None = answer.get("short_answer_text")

    if qtype == "short_answer":
        if not short_ans:
            return False
        norm = short_ans.strip().lower()
        accepted = q.accepted_answers or []
        return any(norm == str(a).strip().lower() for a in accepted)

    # Option-based grading
    correct_ids = set(db.execute(
        select(LmsQuizQuestionOption.id).where(
            LmsQuizQuestionOption.question_id == q.id,
            LmsQuizQuestionOption.is_correct.is_(True),
        )
    ).scalars())

    if qtype in ("single_choice", "true_false"):
        return len(selected) == 1 and selected[0] in correct_ids

    if qtype == "multi_choice":
        return set(selected) == correct_ids

    return False


def next_attempt_number(db: Session, enrollment_id: int, quiz_id: int) -> int:
    """Compute the next attempt_number for a given (enrollment, quiz)."""
    current = db.execute(
        select(LmsQuizAttempt.attempt_number)
        .where(
            LmsQuizAttempt.enrollment_id == enrollment_id,
            LmsQuizAttempt.quiz_id == quiz_id,
        )
        .order_by(LmsQuizAttempt.attempt_number.desc())
        .limit(1)
    ).scalar()
    return (current or 0) + 1


# ============================================================ Course completion

def recalculate_completion(db: Session, enrollment: Enrollment) -> bool:
    """Update ``enrollment.completed_at`` based on lesson_progress
    + course completion_threshold_percent. Returns True if the
    enrollment is now in the "completed" state.

    Completion math:
      - Mandatory lessons only (is_mandatory=true)
      - Across all published chapters + lessons in the course
      - completed_lessons / mandatory_lessons * 100 >= threshold → completed
    """
    course = db.get(Course, enrollment.course_id)
    if not course:
        return False
    threshold = course.completion_threshold_percent or 100

    # Count mandatory lessons under published chapters
    mandatory_lessons = list(db.execute(
        select(Lesson.id).join(Chapter, Lesson.chapter_id == Chapter.id).where(
            Chapter.course_id == course.id,
            Chapter.is_published.is_(True),
            Chapter.is_deleted.is_(False),
            Lesson.is_published.is_(True),
            Lesson.is_deleted.is_(False),
            Lesson.is_mandatory.is_(True),
        )
    ).scalars())

    if not mandatory_lessons:
        return False

    # Count completed mandatory lessons
    completed_ids = set(db.execute(
        select(LessonProgress.lesson_id).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.completed_at.is_not(None),
            LessonProgress.lesson_id.in_(mandatory_lessons),
        )
    ).scalars())

    pct = round((len(completed_ids) / len(mandatory_lessons)) * 100)
    if pct >= threshold and not enrollment.completed_at:
        enrollment.completed_at = datetime.now(timezone.utc)
        return True
    if pct < threshold and enrollment.completed_at:
        # Un-complete (e.g., admin published a new mandatory lesson)
        enrollment.completed_at = None
        return False
    return enrollment.completed_at is not None
