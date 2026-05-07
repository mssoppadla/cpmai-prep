"""v4.4: anonymous exam attempts on free sets.

Makes exam_sessions.user_id nullable and adds an anon_token column so an
unauthenticated visitor can start, navigate, and submit a free exam set.
The session is keyed by a signed cookie on their browser; results are
shown on submit but not persisted to any user account.

Premium sets keep requiring login + active subscription (the service
layer rejects an anon caller for is_premium=true sets before any DB
write).

Forward-only, additive. No existing rows touched.

Revision ID: 0006_anon_attempts
Revises: 0005_faq_lead_extras
"""
from alembic import op


revision = "0006_anon_attempts"
down_revision = "0005_faq_lead_extras"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the NOT NULL on user_id so anonymous sessions can be created.
    # Existing rows (all currently authenticated) keep their non-null ids.
    op.execute("""
        ALTER TABLE exam_sessions
        ALTER COLUMN user_id DROP NOT NULL
    """)
    # Cookie-bound anonymous session key. Indexed because lookups by token
    # happen on every save_answer / get_attempt call from a guest.
    op.execute("""
        ALTER TABLE exam_sessions
        ADD COLUMN IF NOT EXISTS anon_token VARCHAR(64)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_exam_sessions_anon_token
        ON exam_sessions(anon_token)
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0006 is forward-only — anonymous attempts must be preserved."
    )
