"""Ad-campaign attribution columns on payments.

journey_events and leads already record utm_source/medium/campaign;
payments only had the free-text "referred by". With Google/LinkedIn
ads launching, revenue must be attributable per campaign — the three
columns are stamped at order-creation time from the SPA tracker's
session UTMs.

Additive + fully reversible. No backfill: historical rows stay NULL
(attribution unknown).

Revision ID: 0041_payment_utm
Revises: 0040_testimonials
"""
from alembic import op
import sqlalchemy as sa


revision = "0041_payment_utm"
down_revision = "0040_testimonials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("utm_source", sa.String(64)))
    op.add_column("payments", sa.Column("utm_medium", sa.String(64)))
    op.add_column("payments", sa.Column("utm_campaign", sa.String(128)))
    op.create_index("ix_payments_utm_campaign", "payments", ["utm_campaign"])


def downgrade() -> None:
    op.drop_index("ix_payments_utm_campaign", table_name="payments")
    op.drop_column("payments", "utm_campaign")
    op.drop_column("payments", "utm_medium")
    op.drop_column("payments", "utm_source")
