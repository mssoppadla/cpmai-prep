"""Add an admin-only ``notes`` column to ``users``.

The admin Contacts feed (/admin/leads) lets operators jot internal notes
on a contact. Until now only ``leads`` (landing-form submissions) carried
a ``notes`` column, so the editor was disabled for signed-up users
(Google / password). This adds the same free-text field to ``users`` so
internal notes work for every contact regardless of source/role.

Deliberately additive + fully reversible:

  * Plain nullable ``Text`` — NO server_default. Keeps the autogenerate
    drift gate (``compare_type`` / ``compare_server_default``) from
    flagging false drift, mirroring the 0034 approach.
  * NULL simply means "no notes yet".

Revision ID: 0035_user_notes
Revises: 0034_enrollment_podcast_pointer

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0035_user_notes"
down_revision = "0034_enrollment_podcast_pointer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "notes")
