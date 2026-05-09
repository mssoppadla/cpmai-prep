"""Question + QuestionOption models (v4).

New v4 columns are nullable/defaulted so the migration is backward-compatible
with deployments where these tables already contain user-authored content.
"""
import enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, JSON, ForeignKey,
    Enum as SQLEnum, UniqueConstraint, DateTime
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Difficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionType(str, enum.Enum):
    """Whether a question has one correct answer or multiple.

    `single_choice` (default, the historical behaviour): the learner
    sees radio buttons, picks ONE option, scoring is `selected == correct`.

    `multi_choice`: the learner sees checkboxes, picks any number,
    scoring is exact-set match (all correct selected, no incorrect
    selected → 1; otherwise 0). Partial credit not supported in this
    cut. The admin validator requires ≥2 correct options when this
    type is set, otherwise the question is structurally single.
    """
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE  = "multi_choice"


class Question(Base):
    __tablename__ = "questions"

    id          = Column(Integer, primary_key=True)
    stem        = Column(Text, nullable=False)

    topic_id    = Column(Integer, ForeignKey("topics.id"), index=True, nullable=False)

    domain      = Column(String(120), index=True)
    task        = Column(String(160))
    enablers    = Column(JSON, default=list)
    remarks     = Column(Text)
    difficulty  = Column(SQLEnum(Difficulty), default=Difficulty.MEDIUM, nullable=False)
    # See QuestionType. Default preserves single-choice behaviour for every
    # row authored before this column existed.
    question_type = Column(SQLEnum(QuestionType, name="question_type_enum"),
                           default=QuestionType.SINGLE_CHOICE,
                           nullable=False, index=True)
    explanation = Column(Text)

    is_active   = Column(Boolean, default=True, nullable=False, index=True)
    created_by  = Column(Integer, ForeignKey("users.id"))
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True),
                         server_default=func.now(), onupdate=func.now())

    options    = relationship("QuestionOption", back_populates="question",
                              cascade="all, delete-orphan",
                              order_by="QuestionOption.option_letter")
    exam_sets  = relationship("ExamSet", secondary="exam_set_questions",
                              back_populates="questions", viewonly=True)


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (
        UniqueConstraint("question_id", "option_letter", name="uq_question_option_letter"),
    )

    id            = Column(Integer, primary_key=True)
    question_id   = Column(Integer,
                           ForeignKey("questions.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    option_letter = Column(String(2), nullable=False)
    text          = Column(Text, nullable=False)
    is_correct    = Column(Boolean, default=False, nullable=False)
    reasoning     = Column(Text)

    question = relationship("Question", back_populates="options")
