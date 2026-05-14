"""v5.6: add ``resolved_at`` + ``resolved_by`` to assistant_flagged_turns.

Extends the HITL flagged-turn workflow with an explicit resolved
state. Two parties can close a flag:

  * The **user** themselves — they re-read the AI's answer and
    realised it was fine, or they got an admin reply and want to
    close the loop ("thanks, that helped"). Withdrawal-from-the-
    flagger.

  * An **admin** — useful when the user never re-opens the chat after
    flagging (so ``seen_by_user_at`` never gets stamped), or when the
    admin reviews a flag and decides it's invalid without writing a
    user-facing reply ("not actionable; closing").

State machine after this change::

  flagged_at set,  replied_at NULL,  resolved_at NULL → pending
  replied_at set,  resolved_at NULL                   → replied (awaiting user pickup)
  resolved_at set                                     → resolved (hidden from queue)

The existing ``seen_by_user_at`` semantics are unchanged — it still
marks "user opened the widget and saw the admin reply". A user who
sees the reply but doesn't explicitly tap Resolved leaves the flag
in the "replied/seen but not resolved" state; the admin can close
those out themselves with the new admin-resolve endpoint.

``resolved_by`` semantics:

  * NULL                — sentinel, shouldn't happen after this
                          migration; rows pre-dating the column stay
                          NULL until backfilled (we don't backfill;
                          we treat pre-existing flagged-but-not-
                          resolved rows as "still open until someone
                          explicitly resolves them").
  * = row.user_id       — the flagging user resolved their own flag.
  * any other user_id   — an admin (or super-admin) resolved it.

Caller code derives the "who resolved this" label from this column
without needing a separate boolean.

Revision ID: 0021_flagged_turn_resolved
Revises: 0020_payments_generic_provider
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_flagged_turn_resolved"
down_revision = "0020_payments_generic_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both nullable + no default — existing rows stay in their
    # current state (pending/replied/seen) and only get resolved
    # via an explicit user or admin action via the new endpoints.
    op.add_column(
        "assistant_flagged_turns",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assistant_flagged_turns",
        sa.Column("resolved_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
    )
    # Admin queue hides resolved rows by default → the common query
    # is "WHERE resolved_at IS NULL ORDER BY flagged_at ASC". Index
    # accelerates that scan as the table grows. Partial index would
    # be ideal but stays Postgres-only; the plain index works on both
    # Postgres + SQLite (tests).
    op.create_index(
        "ix_flagged_turns_resolved_at",
        "assistant_flagged_turns", ["resolved_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_flagged_turns_resolved_at",
                   table_name="assistant_flagged_turns")
    op.drop_column("assistant_flagged_turns", "resolved_by")
    op.drop_column("assistant_flagged_turns", "resolved_at")
