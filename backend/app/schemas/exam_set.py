from pydantic import BaseModel, Field
from app.models.question import Difficulty


class ExamSetSummaryOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    difficulty: Difficulty
    time_limit_minutes: int
    passing_score: int
    is_premium: bool
    cover_image_url: str | None = None
    question_count: int = 0
    user_attempts: int = 0

    class Config:
        from_attributes = True


class ExamSetAdminIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,138}[a-z0-9]$")
    description: str | None = None
    difficulty: Difficulty = Difficulty.MEDIUM
    time_limit_minutes: int = Field(ge=5, le=300, default=90)
    passing_score: int = Field(ge=0, le=100, default=70)
    is_active: bool = True
    is_premium: bool = False
    display_order: int = 100
    cover_image_url: str | None = None


class AddQuestionsIn(BaseModel):
    question_ids: list[int] = Field(min_length=1)


class ReorderIn(BaseModel):
    """Each item: {question_id: <int>, position: <int>}"""
    items: list[dict]
