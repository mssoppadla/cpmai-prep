"""v5.6: ECO domain-practice support (schema-only, fully reversible).

Adds one nullable column:

  `exam_sessions.practice_domain` — set when an attempt is a focused
  domain-practice drill over a subset of a set's questions (the results-
  screen drill-down). NULL = a normal full-set sitting.

Deliberately schema-only. We do NOT rewrite `questions.domain` here:

  * The exam is scored by ECO domain, and the app resolves a question's
    domain at READ time — canonical codes (D-I … D-V), legacy free-text,
    and blanks all group sensibly without touching stored data (see
    app.core.domains + ExamService._domain_label). So a backfill is a
    convenience, not a correctness requirement.
  * A backfill would mutate existing rows irreversibly (the prior
    free-text values can't be reconstructed on downgrade). Keeping this
    migration additive means `alembic downgrade` is a clean, total
    rollback, and rolling the code back leaves a harmless unused column.

Admins canonicalize existing rows at their own pace via the question
editor's domain dropdown or the bulk export/import round-trip — no
forced, lossy data rewrite.

Revision ID: 0033_eco_domains_practice
Revises: 0032_visitor_insights

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0033_eco_domains_practice"
down_revision = "0032_visitor_insights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_sessions",
        sa.Column("practice_domain", sa.String(length=8), nullable=True),
    )
    op.create_index(
        "ix_exam_sessions_practice_domain",
        "exam_sessions", ["practice_domain"],
    )


def downgrade() -> None:
    op.drop_index("ix_exam_sessions_practice_domain",
                  table_name="exam_sessions")
    op.drop_column("exam_sessions", "practice_domain")
