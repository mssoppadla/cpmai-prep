from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, JSON,
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
    # When set, this attempt is a focused *domain practice* over a subset of
    # the set's questions (only those whose Question.domain matches this ECO
    # domain code, e.g. "D-I"). NULL = a normal full-set sitting. Scoring
    # and the question list both respect this scope — see ExamService.
    practice_domain = Column(String(8), nullable=True, index=True)
    started_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True))
    # Wall-clock deadline as of the last activity event. Kept in sync
    # with remaining_seconds (expires_at = last_activity_at + remaining)
    # so the frontend countdown and the in-exam expiry checks keep
    # working unchanged. While the candidate is AWAY the clock is
    # paused: expires_at goes stale and resume recomputes it from
    # remaining_seconds — liveness checks must use remaining_seconds,
    # not expires_at (see ExamService._draft_is_live).
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    # Active-time budget left, in seconds (pause-on-leave timer). NULL
    # only on legacy rows predating migration 0046.
    remaining_seconds = Column(Integer, nullable=True)
    # When the budget was last charged (heartbeat / answer save / pause).
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    # True when the sitting was finalized by the clock, not a deliberate
    # candidate submit — drives the "Auto-submitted — time expired" label.
    auto_submitted = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="in_progress")
    score  = Column(Integer)
    passed = Column(Boolean)
    time_taken_seconds = Column(Integer)
    # Frozen per-question review payload (list of QuestionResultView
    # dicts) captured at submit, so the result a candidate saw survives
    # later edits to the live questions (reworded stems, changed answer
    # keys, removals from the set). NULL while in progress and on
    # attempts submitted before this column existed — those fall back
    # to live reconstruction in ExamService.get_result.
    result_snapshot = Column(JSON, nullable=True)

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
    # For single_choice questions: a single option_letter (e.g. "B").
    # For multi_choice questions: NULL here, see selected_letters below.
    selected_letter = Column(String(2))
    # For multi_choice questions: a JSON array of letters (e.g. ["A","C"]).
    # NULL means "not answered" or "single_choice question — read
    # selected_letter instead". Empty list means "answered with no
    # selection" (admin-curiosity, scores as 0).
    selected_letters = Column(JSON)
    is_correct = Column(Boolean)
    marked_for_review = Column(Boolean, default=False, nullable=False)
    answered_at = Column(DateTime(timezone=True))

    session = relationship("ExamSession", back_populates="answers")
