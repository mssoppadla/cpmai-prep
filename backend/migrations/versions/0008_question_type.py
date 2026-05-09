"""v5.1: question_type (single/multi-choice) + selected_letters on attempts.

Adds support for multi-correct-answer questions:

  - questions.question_type — enum {single_choice, multi_choice}.
    Default 'single_choice' so every existing row keeps its current
    contract (one correct, scored on radio match).

  - exam_attempt_answers.selected_letters — JSON array of option
    letters for the multi-choice case. Single-choice attempts continue
    to use selected_letter (single string); multi-choice ones populate
    this list and leave selected_letter NULL.

Forward-only, additive — no existing rows touched. The column default
on questions backfills automatically; the new attempts column is
nullable so historical attempts pre-migration aren't disturbed.

Revision ID: 0008_question_type
Revises: 0007_pricing_plans
"""
from alembic import op


revision = "0008_question_type"
down_revision = "0007_pricing_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enum type — Alembic-friendly, idempotent via DO block.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'question_type_enum'
            ) THEN
                CREATE TYPE question_type_enum AS ENUM ('single_choice', 'multi_choice');
            END IF;
        END$$;
    """)
    op.execute("""
        ALTER TABLE questions
        ADD COLUMN IF NOT EXISTS question_type question_type_enum
            NOT NULL DEFAULT 'single_choice'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_questions_question_type
        ON questions(question_type)
    """)
    op.execute("""
        ALTER TABLE exam_attempt_answers
        ADD COLUMN IF NOT EXISTS selected_letters JSONB
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0008 is forward-only — attempt history with selected_letters must "
        "not be discarded, and dropping the questions enum requires "
        "validating every row first."
    )
