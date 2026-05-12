"""v5.5: add users.deleted_at for GDPR soft-delete.

Self-service account deletion under `DELETE /users/me` performs a
soft-delete: the row stays for FK preservation (payments, audit log)
but PII fields are redacted and `is_active=false`, `deleted_at=now()`.

A row with `deleted_at IS NOT NULL` is treated as "this user no longer
exists" by the rest of the app — login is blocked, dashboard 404s.

Revision ID: 0013_users_deleted_at
Revises: 0012_lead_source_chat_callback
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_users_deleted_at"
down_revision = "0012_lead_source_chat_callback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
