"""Create the ``email_templates`` table for the lead → auto-offer reply.

Backs the admin-editable HTML email templates that the lead-capture
automation renders + sends on a consented landing-form sign-up. Templates
are selected by lead ``source`` (intent), with a ``source IS NULL`` row as
the default fallback.

Additive (new table only) + fully reversible.

Revision ID: 0036_email_templates
Revises: 0035_user_notes

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa


revision = "0036_email_templates"
down_revision = "0035_user_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_email_templates_source", "email_templates", ["source"])
    op.create_index("ix_email_templates_is_active", "email_templates",
                    ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_email_templates_is_active", table_name="email_templates")
    op.drop_index("ix_email_templates_source", table_name="email_templates")
    op.drop_table("email_templates")
