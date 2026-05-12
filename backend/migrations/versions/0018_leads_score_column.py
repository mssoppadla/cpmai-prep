"""v5.9: add ``leads.score`` for rule-based lead scoring.

Adds a nullable INTEGER column. Populated by ``calculate_lead_score()``
at insert time; left NULL for any historical row that pre-dates this
migration. Admin can backfill manually by re-saving any old lead via
the notes patch endpoint — that path now recomputes the score.

Why nullable + no backfill: there's only one lead in prod today and the
scoring rules will likely evolve as we observe lead behavior. Forcing
a backfill at migration time would freeze in early-iteration values.
Letting admin opt-in keeps things flexible.

Revision ID: 0018_leads_score_column
Revises: 0017_lead_source_to_values
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_leads_score_column"
down_revision = "0017_lead_source_to_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS score INTEGER
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0016 is forward-only — dropping the score column would drop "
        "admin-curated lead-ranking data."
    )
