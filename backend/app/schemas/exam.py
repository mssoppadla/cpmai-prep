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


class SubmitAttemptOut(BaseModel):
    id: int
    score: int
    passed: bool
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    time_taken_seconds: int
    questions: list[QuestionResultView]
    by_phase: list[PhaseBreakdown]
