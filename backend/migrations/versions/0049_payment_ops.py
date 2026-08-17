"""Payments ops hygiene: refunds, ad-hoc invoices, traceability, webhook health.

Additive only:

* payments.captured_via — HOW a payment reached captured:
  'verify' (browser signature), 'webhook', 'admin' (Mark paid),
  'manual' (manual grant), 'reconcile' (gateway sweep). NULL on
  historical rows. Drives the "manually captured" badge/filter.
  payments is a GUARDED table — column added, ZERO rows changed.
* payment_providers.last_webhook_at — stamped whenever a webhook
  delivery verifies against this config's secret. Powers the per-card
  webhook-health indicator (a listed account that never receives
  webhooks is silently losing captures — 2026-08-17 incident).
* adhoc_invoices — invoices for fully off-platform sales, entered
  manually (buyer name/email, description, amount). Same PDF layout
  and email templates as payment invoices; separate M-numbered series
  (INV-<year>-M<id>) so payment-derived numbers never collide.

Revision ID: 0049_payment_ops
Revises: 0048_payment_invoice

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0049_payment_ops"
down_revision = "0048_payment_invoice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments",
                  sa.Column("captured_via", sa.String(16), nullable=True))
    op.add_column("payment_providers",
                  sa.Column("last_webhook_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.create_table(
        "adhoc_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_number", sa.String(40), nullable=False,
                  unique=True),
        sa.Column("buyer_name", sa.String(160), nullable=False),
        sa.Column("buyer_email", sa.String(240), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False,
                  server_default="INR"),
        sa.Column("gateway_reference", sa.String(120), nullable=True),
        sa.Column("email_status", sa.String(16), nullable=True),
        sa.Column("email_sent_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("adhoc_invoices")
    op.drop_column("payment_providers", "last_webhook_at")
    op.drop_column("payments", "captured_via")
