from pydantic import BaseModel
from app.models.question import Difficulty, QuestionType


class QuestionOptionIn(BaseModel):
    option_letter: str
    text: str
    is_correct: bool = False
    reasoning: str | None = None
    class Config: from_attributes = True


class QuestionOptionOut(BaseModel):
    """During attempt — answers HIDDEN."""
    option_letter: str
    text: str
    class Config: from_attributes = True


class QuestionOptionResultOut(QuestionOptionOut):
    """After submit — full reveal."""
    is_correct: bool
    reasoning: str | None
    selected_by_user: bool = False


class QuestionAttemptView(BaseModel):
    id: int
    stem: str
    topic_id: int
    domain: str | None = None
    task: str | None = None
    difficulty: Difficulty
    # Frontend uses this to render radio (single) vs checkbox (multi).
    question_type: QuestionType = QuestionType.SINGLE_CHOICE
    options: list[QuestionOptionOut]
    class Config: from_attributes = True


class QuestionResultView(BaseModel):
    id: int
    stem: str
    topic_id: int
    domain: str | None = None
    task: str | None = None
    enablers: list[str] = []
    remarks: str | None = None
    difficulty: Difficulty
    question_type: QuestionType = QuestionType.SINGLE_CHOICE
    explanation: str | None = None
    options: list[QuestionOptionResultOut]
    is_user_correct: bool


class QuestionAdminIn(BaseModel):
    stem: str
    topic_id: int
    domain: str | None = None
    task: str | None = None
    enablers: list[str] = []
    remarks: str | None = None
    difficulty: Difficulty = Difficulty.MEDIUM
    # Defaults to single_choice for backward compatibility — admins
    # who don't set the field get the historical behaviour.
    question_type: QuestionType = QuestionType.SINGLE_CHOICE
    explanation: str | None = None
    options: list[QuestionOptionIn]
    is_active: bool = True


class _ExamSetRefForQuestion(BaseModel):
    """Mirrors ExamSetRef in schemas/exam_set.py. Defined here to avoid
    a circular import (exam_set.py already imports QuestionAdminOut).
    Same shape — admin UI treats them interchangeably."""
    id: int
    slug: str
    name: str


class QuestionAdminOut(QuestionAdminIn):
    id: int
    # Sets this question is currently tagged into. Surfaced in admin so
    # the operator can spot duplicates ("this question is already in
    # Set 1, Set 5") before adding it to yet another set. Empty list
    # means the question is unattached. Populated by the endpoint via
    # a bulk join to avoid N+1 queries.
    in_sets: list[_ExamSetRefForQuestion] = []
    class Config: from_attributes = True
