from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime,
    UniqueConstraint, CheckConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ExamSession(Base):
    __tablename__ = "exam_sessions"
    id = Column(Integer, primary_key=True)
    # Either user_id (signed-in attempt) OR anon_token (cookie-bound guest
    # attempt) is set. Service layer enforces exactly-one-of.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    anon_token = Column(String(64), nullable=True, index=True)
    exam_set_id = Column(Integer, ForeignKey("exam_sets.id"), index=True)
    started_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True))
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), nullable=False, default="in_progress")
    score  = Column(Integer)
    passed = Column(Boolean)
    time_taken_seconds = Column(Integer)

    answers = relationship("ExamAttemptAnswer", back_populates="session",
                           cascade="all, delete-orphan")


class ExamAttemptAnswer(Base):
    __tablename__ = "exam_attempt_answers"
    __table_args__ = (
        UniqueConstraint("exam_session_id", "question_id",
                         name="uq_attempt_question"),
    )
    id = Column(Integer, primary_key=True)
    exam_session_id = Column(Integer,
                             ForeignKey("exam_sessions.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    selected_letter = Column(String(2))
    is_correct = Column(Boolean)
    marked_for_review = Column(Boolean, default=False, nullable=False)
    answered_at = Column(DateTime(timezone=True))

    session = relationship("ExamSession", back_populates="answers")
