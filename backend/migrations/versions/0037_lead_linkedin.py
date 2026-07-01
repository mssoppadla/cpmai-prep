"""Add a ``linkedin_id`` column to ``leads``.

The landing lead form now asks for a LinkedIn id/URL (in place of the WhatsApp
number) so we can serve aspirants better and share relevant prep documents.
Admins see it on the Contacts and Users screens.

Deliberately additive + reversible, matching 0035:

  * Plain nullable ``String(255)`` — NO server_default, so the autogenerate
    drift gate doesn't flag false drift.
  * NULL means "no LinkedIn provided". Existing rows (and the existing
    ``whatsapp_number`` column) are untouched — no data is altered.

Revision ID: 0037_lead_linkedin
Revises: 0036_email_templates
"""
from alembic import op
import sqlalchemy as sa


revision = "0037_lead_linkedin"
down_revision = "0036_email_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("linkedin_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "linkedin_id")
