from sqlalchemy import Column, Integer, String, DateTime, JSON, Index
from sqlalchemy.sql import func
from app.core.database import Base


class JourneyEvent(Base):
    __tablename__ = "journey_events"
    __table_args__ = (
        Index("ix_je_user_time", "user_id", "created_at"),
        Index("ix_je_anon_time", "anon_id", "created_at"),
    )
    id = Column(Integer, primary_key=True)
    event = Column(String(64), nullable=False)
    user_id = Column(Integer, index=True)
    anon_id = Column(String(36), index=True)
    session_id = Column(String(36), index=True)
    request_id = Column(String(36))
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
