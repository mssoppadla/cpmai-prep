"""Add the "listen as podcast" resume pointer to enrollments.

Adds two nullable columns to ``enrollments``:

  ``podcast_lesson_id``        — the lesson the learner was listening to
  ``podcast_position_seconds`` — how far into it (seconds)

These track the audio-only "podcast" playthrough independently of the
per-lesson video ``last_position_seconds``, so listening and watching
don't clobber each other's resume point.

Deliberately additive + fully reversible:

  * Both columns are plain nullable integers — NO foreign key and NO
    server_default. That keeps ``compare_type`` / ``compare_server_default``
    autogenerate (the migration-drift gate) from flagging false drift, and
    avoids a referential constraint that would complicate lesson deletes.
    A NULL pointer simply means "podcast not started"; the app resolves a
    stale/missing lesson id by restarting from the first track.

Revision ID: 0034_enrollment_podcast_pointer
Revises: 0033_eco_domains_practice

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_enrollment_podcast_pointer"
down_revision = "0033_eco_domains_practice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrollments",
        sa.Column("podcast_lesson_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "enrollments",
        sa.Column("podcast_position_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrollments", "podcast_position_seconds")
    op.drop_column("enrollments", "podcast_lesson_id")
