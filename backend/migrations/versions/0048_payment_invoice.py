"""Invoice columns on payments (additive only).

* invoice_number        — assigned on first invoice generation
                          (INV-<year>-<payment id>); NULL until then.
* invoice_email_status  — NULL (never attempted) | queued | sent | failed
                          | skipped. Drives the admin payments column.
* invoice_email_sent_at — when the mail actually left.

payments is a GUARDED table — columns added, ZERO rows changed; the
deploy guard verifies +0. NEVER add deletes here.

Revision ID: 0048_payment_invoice
Revises: 0047_gateway_listing

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0048_payment_invoice"
down_revision = "0047_gateway_listing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments",
                  sa.Column("invoice_number", sa.String(40), nullable=True,
                            unique=True))
    op.add_column("payments",
                  sa.Column("invoice_email_status", sa.String(16),
                            nullable=True))
    op.add_column("payments",
                  sa.Column("invoice_email_sent_at",
                            sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "invoice_email_sent_at")
    op.drop_column("payments", "invoice_email_status")
    op.drop_column("payments", "invoice_number")
