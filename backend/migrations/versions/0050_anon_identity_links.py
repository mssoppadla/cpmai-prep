"""anon_identity_links — browser anon-id → account map.

Additive only: creates one new table, touches ZERO existing rows.
Written at login/signup when the browser presents its persistent
anonymous id (X-Anon-ID); read by the Contacts traffic widget to
classify visitors as known vs anonymous. Guarded tables untouched.

Revision ID: 0050_anon_links
Revises: 0049_payment_ops

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0050_anon_links"
down_revision = "0049_payment_ops"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "anon_identity_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anon_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_anon_identity_links_anon_id",
                    "anon_identity_links", ["anon_id"], unique=True)
    op.create_index("ix_anon_identity_links_user_id",
                    "anon_identity_links", ["user_id"])


def downgrade():
    op.drop_index("ix_anon_identity_links_user_id",
                  table_name="anon_identity_links")
    op.drop_index("ix_anon_identity_links_anon_id",
                  table_name="anon_identity_links")
    op.drop_table("anon_identity_links")
