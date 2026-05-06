"""v4.3: editable FAQs + lead extras (whatsapp / country code).

Adds:
  - faq_items table for landing-page FAQs (admin-editable)
  - leads.whatsapp_number  (string, nullable)
  - leads.country_code     (string, nullable, e.g. "+91")

Forward-only, additive. No existing rows touched.

Revision ID: 0005_faq_lead_extras
Revises: 0004_google_auth
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_faq_lead_extras"
down_revision = "0004_google_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FAQs
    op.execute("""
        CREATE TABLE IF NOT EXISTS faq_items (
            id            SERIAL PRIMARY KEY,
            question      TEXT NOT NULL,
            answer        TEXT NOT NULL,
            display_order INT  NOT NULL DEFAULT 100,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_faq_items_display_order "
               "ON faq_items(display_order)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_faq_items_is_active "
               "ON faq_items(is_active)")

    # Lead form: WhatsApp + country code
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS country_code     VARCHAR(8)")
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_number  VARCHAR(32)")


def downgrade() -> None:
    raise NotImplementedError(
        "0005 is forward-only — FAQ rows + lead WhatsApp data must be preserved."
    )
