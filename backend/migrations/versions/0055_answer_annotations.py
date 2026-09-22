"""exam_attempt_answers.annotations — the learner's highlight / strike
marks on a question, kept after submission so the results review shows
the page exactly as they left it. Previously browser-only (localStorage)
and wiped on submit.

JSON: {"stem": [{"start": 0, "end": 12, "kind": "highlight"}],
       "option-A": [...], ...}   — same shape the exam page uses.

Additive, nullable; exam_attempt_answers is a guarded table (no row
deletes here).

Revision ID: 0055_answer_annotations (23 chars ≤ 32 ✓).
"""
from alembic import op
import sqlalchemy as sa

revision = "0055_answer_annotations"
down_revision = "0054_programs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("exam_attempt_answers",
                  sa.Column("annotations", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("exam_attempt_answers", "annotations")
