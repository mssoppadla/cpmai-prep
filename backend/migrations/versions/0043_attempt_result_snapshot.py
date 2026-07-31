"""Attempt-level result snapshot (schema-only, fully reversible).

Adds one nullable column:

  `exam_sessions.result_snapshot` — the full per-question review payload
  (list of QuestionResultView dicts: stem, options with correct flags
  and reasoning, explanation, domain, verdicts) frozen at submit time.

Why: results were reconstructed from LIVE question rows on every view,
so editing a question (or removing it from a set) silently rewrote what
past candidates saw in their review — changed answer keys made old
verdicts contradict the displayed marking, and removed questions
vanished from the review while the frozen score stayed. With the
snapshot, a submitted attempt is a clean historical record; the live
set evolves freely for future candidates.

NULL = attempt submitted before this feature (get_result falls back to
the old live reconstruction) or still in progress. No backfill is
possible — the pre-edit content of already-mutated questions is gone.

Revision ID: 0043_attempt_result_snapshot
Revises: 0042_canonical_question_domains

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0043_attempt_result_snapshot"
down_revision = "0042_canonical_question_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_sessions",
        sa.Column("result_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exam_sessions", "result_snapshot")
