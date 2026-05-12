"""v5.5: assistant_flagged_turns table for human-in-the-loop replies.

When the AI gives an unhelpful answer, the user clicks "Wasn't helpful"
on the turn, optionally adds a note about what was wrong, and the flag
lands in this table. An admin picks it up from /admin/chat-history/
flagged, writes a follow-up reply, and the user sees it on their next
chat-widget open (in-app delivery only — no email infrastructure yet).

Schema decision: separate table rather than columns on assistant_logs.
Most assistant log rows never get flagged, so adding 5+ NULL columns to
every row was wasteful. Separating also lets admins query the queue
without scanning the full chat log.

Three explicit states from the timestamps:
  • flagged_at set, replied_at NULL    → pending (admin queue)
  • replied_at set, seen_by_user_at NULL → awaiting user pickup (red dot)
  • seen_by_user_at set                 → closed

UNIQUE(assistant_log_id) — a turn can only be flagged once. Re-clicking
"Wasn't helpful" is a no-op on the second submit.

Revision ID: 0015_hitl_flagged_turns
Revises: 0014_lead_source_name_fix

Note: revision id stays under VARCHAR(32) for alembic_version
(this one's 23 chars). Originally drafted as 0013_*; rebased to slot
0015 after main picked up 0013_users_deleted_at (GDPR) and
0014_lead_source_name_fix (leadsource enum-name fix).
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_hitl_flagged_turns"
down_revision = "0014_lead_source_name_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_flagged_turns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("assistant_log_id", sa.Integer,
                  sa.ForeignKey("assistant_logs.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        # Denormalized for fast `WHERE user_id = ?` queries on the admin
        # flag-count overview. Set to NULL if the user is later deleted
        # (GDPR DELETE /users/me) — the flag row survives for admin audit.
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("flag_note", sa.Text, nullable=True),
        sa.Column("flagged_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("admin_reply", sa.Text, nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True,
                  index=True),
        sa.Column("replied_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("seen_by_user_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Common admin-queue query: pending flags oldest-first.
    op.create_index(
        "ix_flagged_turns_pending",
        "assistant_flagged_turns", ["flagged_at"],
        postgresql_where=sa.text("replied_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_flagged_turns_pending", table_name="assistant_flagged_turns")
    op.drop_table("assistant_flagged_turns")
