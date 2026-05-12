"""v5.9: add lowercase VALUE variants to leadsource enum.

Setup for the next migration (0017) which normalizes existing leads
rows from the historical uppercase NAMES (``LANDING_HERO`` etc., as
stored by SQLAlchemy's default ``SQLEnum`` serialization) to the new
lowercase VALUES.

Why this is split from the data migration: Postgres requires
``ALTER TYPE … ADD VALUE`` to commit before the new value can be
referenced in DML. Even in PG 12+ where ``ADD VALUE`` is allowed
inside a transaction, ``UPDATE leads SET source = 'landing_hero'``
in the SAME transaction raises ``invalid input value for enum``. So
we split: this migration adds the values; 0017 does the data
migration in a fresh transaction.

``chat_callback`` is already in the enum (added by 0012) — the
``IF NOT EXISTS`` clauses keep this idempotent.

The original uppercase NAMES stay in the enum (Postgres has no
``DROP VALUE`` short of a destructive type rebuild). They become
unused dead code at the DB level once 0017 + the model change land.
Harmless.

Revision ID: 0016_lead_source_add_lower
Revises: 0015_hitl_flagged_turns
"""
from alembic import op


revision = "0016_lead_source_add_lower"
down_revision = "0015_hitl_flagged_turns"
branch_labels = None
depends_on = None


# Must mirror the lowercase VALUE strings on LeadSource. Keep this list
# next to the migration rather than importing the enum — that way the
# migration is decoupled from future code changes that might rename or
# remove members.
_VALUES = (
    "landing_hero",
    "newsletter",
    "exit_intent",
    "gated_download",
    "blog",
    "pricing_page",
    "exam_preview",
    "demo_request",
    # chat_callback already in enum (added by migration 0012) — listed
    # here for completeness; the IF NOT EXISTS keeps it idempotent.
    "chat_callback",
)


def upgrade() -> None:
    for v in _VALUES:
        op.execute(f"ALTER TYPE leadsource ADD VALUE IF NOT EXISTS '{v}'")


def downgrade() -> None:
    raise NotImplementedError(
        "0016 is forward-only — Postgres has no DROP VALUE for enums "
        "without a destructive type rebuild."
    )
