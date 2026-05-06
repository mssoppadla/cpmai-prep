"""v4.2: Google sign-in — make password_hash nullable, add google_id.

Backward-compatible additive migration. Existing rows are not touched —
their password_hash stays populated, google_id stays NULL until they
actually sign in with Google.

The DDL uses IF [NOT] EXISTS / IS NOT NULL guards so it is safe to run
on databases where the schema was previously evolved by hand
(via Base.metadata.create_all() during early dev) — no error if the
column is already there.

Revision ID: 0004_google_auth
Revises: 0003_payment_providers
"""
from alembic import op


revision = "0004_google_auth"
down_revision = "0003_payment_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop NOT NULL on password_hash — Google-only accounts have no password.
    # `DROP NOT NULL` is a no-op when the column is already nullable.
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")

    # Add google_id with a unique index. IF NOT EXISTS guards make this
    # safe on a DB where create_all() already added the column.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(64)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id "
        "ON users(google_id)"
    )


def downgrade() -> None:
    # Forward-only: dropping google_id would lose linkage data.
    raise NotImplementedError(
        "0004 is forward-only — Google linkage data must be preserved."
    )
