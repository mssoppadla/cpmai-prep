"""Testimonials table — landing-page carousel cards.

Admin-managed rows (photo, name, role, quote, external proof link)
rendered in the public landing-page carousel. Same shape as faq_items
(display_order + is_active for ordering/hiding) plus the media/link
columns.

Additive + fully reversible.

Revision ID: 0040_testimonials
Revises: 0039_email_lead_suppress
"""
from alembic import op
import sqlalchemy as sa


revision = "0040_testimonials"
down_revision = "0039_email_lead_suppress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "testimonials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=160), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False,
                  server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_testimonials_display_order", "testimonials",
                    ["display_order"])
    op.create_index("ix_testimonials_is_active", "testimonials",
                    ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_testimonials_is_active", table_name="testimonials")
    op.drop_index("ix_testimonials_display_order", table_name="testimonials")
    op.drop_table("testimonials")
