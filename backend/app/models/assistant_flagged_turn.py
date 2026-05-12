"""HITL: a user-flagged chat turn awaiting / completed admin reply.

See migration 0013_hitl_flagged_turns for schema rationale. Three
explicit states live on the row:

  flagged_at set,  replied_at NULL          → pending
  replied_at set,  seen_by_user_at NULL     → reply delivered, unread
  seen_by_user_at set                       → closed
"""
from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class AssistantFlaggedTurn(Base):
    __tablename__ = "assistant_flagged_turns"
    __table_args__ = (
        # Mirrors the partial index in the migration (Postgres-only).
        # SQLite tests don't honor postgresql_where; that's OK — the
        # full index still helps and the partiality is a prod-only
        # optimization.
        Index("ix_flagged_turns_pending", "flagged_at"),
    )

    id = Column(Integer, primary_key=True)
    assistant_log_id = Column(Integer,
                              ForeignKey("assistant_logs.id", ondelete="CASCADE"),
                              nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                     nullable=True, index=True)
    flag_note = Column(Text, nullable=True)
    flagged_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False, index=True)
    admin_reply = Column(Text, nullable=True)
    replied_at = Column(DateTime(timezone=True), nullable=True, index=True)
    replied_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True)
    seen_by_user_at = Column(DateTime(timezone=True), nullable=True)
