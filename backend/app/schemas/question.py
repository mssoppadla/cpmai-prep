from pydantic import BaseModel
from app.models.question import Difficulty


class QuestionOptionIn(BaseModel):
    option_letter: str
    text: str
    is_correct: bool = False
    reasoning: str | None = None


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
    explanation: str | None = None
    options: list[QuestionOptionIn]
    is_active: bool = True


class QuestionAdminOut(QuestionAdminIn):
    id: int
    class Config: from_attributes = True
