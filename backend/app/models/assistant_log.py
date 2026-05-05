from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float, Numeric
from sqlalchemy.sql import func
from app.core.database import Base


class AssistantLog(Base):
    __tablename__ = "assistant_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    anon_id = Column(String(36), index=True)
    intent = Column(String(32), nullable=False)
    intent_confidence = Column(Float, nullable=False)
    provider = Column(String(80), nullable=False)
    model    = Column(String(120))
    redacted_input  = Column(Text, nullable=False)
    response_preview = Column(Text, nullable=False)
    tokens_in  = Column(Integer)
    tokens_out = Column(Integer)
    cost_usd   = Column(Numeric(10, 6))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
