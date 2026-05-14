"""HITL: a user-flagged chat turn awaiting / completed admin reply.

See migration 0013_hitl_flagged_turns for the original schema.
Migration 0021_flagged_turn_resolved added the ``resolved_at`` +
``resolved_by`` columns that close the flag from either side
(user or admin), independent of whether an admin reply was written.

Four-state machine on the row's timestamps:

  flagged_at set, replied_at NULL, resolved_at NULL → **pending**
                                                       (admin queue shows)
  replied_at set, resolved_at NULL                  → **replied**
                                                       (admin wrote a reply; user sees red dot;
                                                        admin queue hides unless include_replied)
  resolved_at set                                   → **resolved**
                                                       (closed by user or admin;
                                                        admin queue hides unless include_resolved)
  seen_by_user_at set                               → an in-band signal that the user opened
                                                       the chat after the admin reply landed.
                                                       Used only for the red-dot indicator;
                                                       does NOT imply "resolved".

``resolved_by`` semantics:

  * NULL                — row pre-dates the resolve feature; treat as
                          "still open until someone explicitly resolves".
  * = row.user_id       — the flagging user resolved their own flag
                          ("thanks, that helped" / "withdrawing").
  * any other user_id   — an admin (or super-admin) resolved it
                          ("not actionable" / "closed without reply").

Callers derive the "who resolved this" label without a separate
boolean: compare ``resolved_by`` to ``user_id`` on the row.
"""
from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class AssistantFlaggedTurn(Base):
    __tablename__ = "assistant_flagged_turns"
    __table_args__ = (
        # Mirrors the partial index in the original migration (Postgres-
        # only). SQLite tests don't honor postgresql_where; that's OK —
        # the full index still helps and the partiality is a prod-only
        # optimization.
        Index("ix_flagged_turns_pending", "flagged_at"),
        # Added by 0021_flagged_turn_resolved. Speeds up the common
        # admin-queue scan "WHERE resolved_at IS NULL".
        Index("ix_flagged_turns_resolved_at", "resolved_at"),
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
    # Resolved state — either party can stamp these. See module
    # docstring for the four-state machine.
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                         nullable=True)
