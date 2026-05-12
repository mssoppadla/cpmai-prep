"""Exam set + many-to-many join table (v4).

Admins curate sets and link questions to them. A question can belong to many sets.
Existing exam_sessions get a nullable exam_set_id so historical attempts remain valid.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, ForeignKey, Enum as SQLEnum,
    DateTime, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from app.models.question import Difficulty


class ExamSet(Base):
    __tablename__ = "exam_sets"

    id                  = Column(Integer, primary_key=True)
    name                = Column(String(120), unique=True, nullable=False)
    slug                = Column(String(140), unique=True, nullable=False, index=True)
    description         = Column(Text)
    difficulty          = Column(SQLEnum(Difficulty), default=Difficulty.MEDIUM)
    time_limit_minutes  = Column(Integer, default=90, nullable=False)
    passing_score       = Column(Integer, default=70, nullable=False)
    is_active           = Column(Boolean, default=True, nullable=False, index=True)
    is_premium          = Column(Boolean, default=False, nullable=False)
    display_order       = Column(Integer, default=100, nullable=False)
    cover_image_url     = Column(String(500))
    created_by          = Column(Integer, ForeignKey("users.id"))
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True),
                                 server_default=func.now(), onupdate=func.now())

    questions = relationship("Question", secondary="exam_set_questions",
                             back_populates="exam_sets")


class ExamSetQuestion(Base):
    __tablename__ = "exam_set_questions"
    # No explicit UniqueConstraint: the composite PK (exam_set_id, question_id)
    # already enforces uniqueness. Postgres collapses the two when create_all
    # emits both, which previously caused `alembic check` to report drift
    # between the model (claims a separate UQ) and the DB (just the PK).
    __table_args__ = (
        Index("ix_exam_set_questions_set_position", "exam_set_id", "position"),
    )

    exam_set_id = Column(Integer, ForeignKey("exam_sets.id", ondelete="CASCADE"),
                         primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"),
                         primary_key=True)
    position    = Column(Integer, default=0, nullable=False)
    added_at    = Column(DateTime(timezone=True), server_default=func.now())
    added_by    = Column(Integer, ForeignKey("users.id"))
