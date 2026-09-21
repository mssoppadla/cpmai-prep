"""Programs — a course that wraps other courses.

``courses.is_program`` marks a course as a Program (master course).
``program_courses`` lists the courses it includes, ordered, one level
deep (a program can't include another program — enforced in the API).

Access is DERIVED, not copied: a learner who holds a live enrollment on
the program (bought, granted, free, or via a plan that bundles it) gets
an implicit ``source='program'`` enrollment on each included course,
re-validated on every read exactly like subscription-derived rows. A
course the learner bought separately keeps its own row and is never
revoked by program changes.

Revision ID: 0054_programs (13 chars ≤ 32 ✓).
"""
from alembic import op
import sqlalchemy as sa

revision = "0054_programs"
down_revision = "0053_free_preview_clip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column(
        "is_program", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "program_courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("program_id", sa.Integer(),
                  sa.ForeignKey("courses.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("course_id", sa.Integer(),
                  sa.ForeignKey("courses.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("added_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("added_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("program_id", "course_id",
                            name="uq_program_courses_program_course"),
    )
    op.create_index("ix_program_courses_program_id", "program_courses", ["program_id"])
    op.create_index("ix_program_courses_course_id", "program_courses", ["course_id"])


def downgrade() -> None:
    op.drop_index("ix_program_courses_course_id", table_name="program_courses")
    op.drop_index("ix_program_courses_program_id", table_name="program_courses")
    op.drop_table("program_courses")
    op.drop_column("courses", "is_program")
