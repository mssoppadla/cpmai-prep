"""v5.3: per-user chat daily-limit override.

Adds `users.daily_chat_limit_override` (nullable int). Admin can give
specific users a higher (or lower) daily chat cap without changing the
global `chat.daily_limit.authenticated` setting.

The rate-limit logic (in AssistantGuardrails.check_daily_limit) reads
the override first; falls back to the global setting if NULL.

Forward-only, additive. Default NULL — existing users keep the global
cap with no behaviour change.

Revision ID: 0010_user_daily_chat_override
Revises: 0009_rag_chunks
"""
from alembic import op


revision = "0010_user_daily_chat_override"
down_revision = "0009_rag_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS daily_chat_limit_override INTEGER
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0010 is forward-only — admin-set overrides represent operator "
        "decisions that should not be silently dropped."
    )
