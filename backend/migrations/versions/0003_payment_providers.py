"""v4.1: payment_providers — backward-compatible additive migration.

Revision ID: 0003_payment_providers
Revises: 0002_v4
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_payment_providers"
down_revision = "0002_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_providers",
        sa.Column("id",            sa.Integer(),    primary_key=True),
        sa.Column("name",          sa.String(80),   nullable=False, unique=True),
        sa.Column("provider_type", sa.String(32),   nullable=False),
        sa.Column("mode",          sa.String(16),   nullable=False, server_default="test"),
        sa.Column("display_name",  sa.String(120)),
        sa.Column("public_key",    sa.String(120)),
        sa.Column("api_secret_encrypted",     sa.LargeBinary()),
        sa.Column("webhook_secret_encrypted", sa.LargeBinary()),
        sa.Column("config",        sa.JSON()),
        sa.Column("is_enabled",    sa.Boolean(),    nullable=False, server_default=sa.true()),
        sa.Column("priority",      sa.Integer(),    nullable=False, server_default="100"),
        sa.Column("created_by",    sa.Integer(),    sa.ForeignKey("users.id")),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payment_providers_is_enabled",
                    "payment_providers", ["is_enabled"])


def downgrade() -> None:
    raise NotImplementedError("Forward-only.")
