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
    user_answers: dict[int, str | None]


class AnswerIn(BaseModel):
    question_id: int
    selected_letter: str | None
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
