from sqlalchemy import Column, Integer, ForeignKey, DateTime, JSON, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    score = Column(Integer)
    correct_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    answers = Column(JSON)                     # list[{question_id, selected, correct}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
