"""v4 schema marker — questions/exam_sets/leads metadata.

Stub revision. Original v4 schema additions (question metadata, exam_set
+ link table, lead capture) were rolled into the create_all() baseline
during early dev. This revision exists so the alembic chain matches the
historical numbering used by the patches.

Revision ID: 0002_v4
Revises: 0001_baseline
"""

revision = "0002_v4"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: schema additions are part of the baseline create_all().
    pass


def downgrade() -> None:
    raise NotImplementedError("Forward-only.")
