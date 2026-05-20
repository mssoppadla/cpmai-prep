"""v6.6: courses.discussion_url (course-level default that lessons inherit).

Operator UX: setting a Discord/forum URL per-lesson is tedious when the
whole course shares one channel. Adds a course-level default; lessons
inherit unless they specifically override at the lesson level.

The cascade is computed at the API edge (public lesson endpoint):
  effective_discussion_url = lesson.discussion_url or course.discussion_url

Schema-level the two columns are independent — we don't materialise the
fallback in lesson rows because that would mean updating every lesson
row when the course's URL changes.

Per contract:
  - M-1: additive only (new nullable column)
  - M-2: downgrade NotImplementedError
  - M-3: single transaction

Revision ID: 0029_course_discussion (21 chars).
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_course_discussion"
down_revision = "0028_plan_courses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("discussion_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0029_course_discussion: downgrade is intentionally unimplemented. "
        "Dropping the column would lose every operator's configured "
        "Discord / forum URL for course-level discussions."
    )
