"""v6.5: plan_courses M:N table (bundle exam sets + courses in one Plan).

The Plans table already supports bundling exam sets (via plan_exam_sets)
and has a ``bundle_type`` field with values ``exam_bundle / course_bundle
/ custom``. Until this migration, courses could only link to a SINGLE
plan via ``courses.plan_id`` (1:N) — which broke the symmetry with
exam sets and prevented "one course in multiple bundles".

This migration adds ``plan_courses`` mirroring ``plan_exam_sets`` exactly.

  plan_courses (
    id          serial PK,
    tenant_id   FK tenants  (per contract I-1),
    plan_id     FK plans    (cascade),
    course_id   FK courses  (cascade),
    added_at    timestamptz default now,
    added_by    FK users    (set null),
    UNIQUE (plan_id, course_id)
  )

We keep ``courses.plan_id`` for backward compat / "primary plan" hinting,
but the M:N join is the source of truth for "is this course in plan X?".

Per contract:
  - I-1: tenant_id on every new table
  - M-1, M-2, M-3: additive only, downgrade NotImplementedError, single
    transaction

Revision ID: 0028_plan_courses (16 chars ≤ 32 ✓).
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_plan_courses"
down_revision = "0027_lms_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_courses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("plan_id",   sa.Integer,
                  sa.ForeignKey("plans.id",   ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("course_id", sa.Integer,
                  sa.ForeignKey("courses.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("added_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("added_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("plan_id", "course_id",
                            name="uq_plan_courses_plan_course"),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0028_plan_courses: downgrade is intentionally unimplemented. "
        "Dropping plan_courses would silently break course access for "
        "every user with a subscription to a plan that bundles courses. "
        "To revert, write a forward migration that exports + archives "
        "the links first."
    )
