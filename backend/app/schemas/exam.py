"""Exam attempt schemas — answers strictly hidden during attempt."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from app.schemas.exam_set import ExamSetSummaryOut
from app.schemas.question import QuestionAttemptView, QuestionResultView


AttemptStatus = Literal["in_progress", "submitted", "expired"]


class ExamAttemptOut(BaseModel):
    id: int
    exam_set: ExamSetSummaryOut
    started_at: datetime
    expires_at: datetime
    status: AttemptStatus
    questions: list[QuestionAttemptView]
    # The user's current selections, keyed by question_id. For
    # single_choice questions the value is the option_letter (or None).
    # For multi_choice questions the value is a sorted comma-separated
    # string of letters (e.g. "A,C") so the wire shape stays
    # `dict[int, str | None]` and the frontend's existing typing
    # doesn't break — the multi-choice page renders by splitting on ','.
    # Empty list / no selection → None.
    user_answers: dict[int, str | None]


class AnswerIn(BaseModel):
    """Save-answer payload.

    Single-choice questions populate `selected_letter`. Multi-choice
    populate `selected_letters` (a list of letters; empty list = no
    selection). The server picks the right field based on the
    question's type — sending the wrong shape returns 400.
    """
    question_id: int
    selected_letter: str | None = None
    selected_letters: list[str] | None = None
    marked_for_review: bool = False


class PhaseBreakdown(BaseModel):
    topic_code: str
    topic_name: str
    correct: int
    total: int
    percent: int


class DomainBreakdown(BaseModel):
    """Per-domain score breakdown. The CPMAI ECO is organised by domain,
    so this is what the results screen surfaces.

    `domain` is the canonical ECO domain code (e.g. "D-I"), or the raw
    stored value for legacy rows, or "Unassigned" when blank. The frontend
    uses it both as the review filter key and to build the
    "practice this domain" link. `domain_name` is the human label.

    `practiceable` is true only for real ECO domain codes — the results
    screen shows a "Practice this domain" action for those rows."""
    domain: str
    domain_name: str
    practiceable: bool
    correct: int
    total: int
    percent: int


class SubmitAttemptOut(BaseModel):
    id: int
    score: int
    passed: bool
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    time_taken_seconds: int
    questions: list[QuestionResultView]
    # by_phase: CPMAI-phase (topic) rollup — kept for backward compatibility.
    # by_domain: ECO-domain rollup — what the results UI displays.
    by_phase: list[PhaseBreakdown]
    by_domain: list[DomainBreakdown]
    # The set this attempt was taken on — lets the results screen offer
    # "retake full exam" and "practice this domain" deep-links. None only
    # for legacy attempts with no set.
    exam_set_slug: str | None = None
    exam_set_name: str | None = None
    # The domain this attempt was scoped to, if it was a domain-practice
    # attempt (vs a full-set sitting). None for full sittings.
    practice_domain: str | None = None


class AttemptHistoryOut(BaseModel):
    """One past (submitted) attempt, for the learner's exam-history list.
    Lightweight — the full per-domain breakdown + review lives on the
    results screen, reached via this `id`."""
    id: int
    exam_set_name: str | None = None
    exam_set_slug: str | None = None
    # Set when this was a domain-practice drill rather than a full sitting.
    practice_domain: str | None = None
    score: int
    passed: bool
    total_questions: int
    correct_count: int
    time_taken_seconds: int
    submitted_at: datetime
