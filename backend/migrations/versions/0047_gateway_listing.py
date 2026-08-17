"""Gateway listing control-plane columns (multi-gateway Phase 1).

See docs/payments-multi-gateway-spec.md §2.1. Additive only:

* payment_providers.listed_for_inr / listed_for_intl /
  intl_rank — which entries are SELLABLE on each rail and their order.
  "Enabled" (existing is_enabled) stays the service-past-payments flag;
  listing is the sell-new-payments flag, so a suspended gateway can be
  delisted in seconds while refunds/webhooks keep working.
* payments.provider_config_id — WHICH account minted this payment.
  provider_name ("razorpay") can't distinguish Personal-Razorpay from
  Company-Razorpay; refunds and webhook verification need to. Nullable:
  historical rows stay NULL and resolve via the legacy provider_name
  path. payments is a GUARDED table — this adds a column, changes ZERO
  rows; deploy guard verifies +0. NEVER add deletes here.

Backfill (idempotent UPDATEs): the entries currently referenced by
payment.active_provider_id / payment.non_inr_provider_id get their
listing flags set so post-migration routing is byte-identical to
pre-migration.

Revision ID: 0047_gateway_listing
Revises: 0046_pause_timer

Note: revision id stays under VARCHAR(32) for alembic_version.
"""
from alembic import op
import sqlalchemy as sa

revision = "0047_gateway_listing"
down_revision = "0046_pause_timer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payment_providers",
                  sa.Column("listed_for_inr", sa.Boolean(), nullable=False,
                            server_default=sa.false()))
    op.add_column("payment_providers",
                  sa.Column("listed_for_intl", sa.Boolean(), nullable=False,
                            server_default=sa.false()))
    op.add_column("payment_providers",
                  sa.Column("intl_rank", sa.Integer(), nullable=False,
                            server_default="100"))
    op.add_column("payments",
                  sa.Column("provider_config_id", sa.Integer(),
                            sa.ForeignKey("payment_providers.id"),
                            nullable=True))

    # Backfill listing flags from the live routing settings so behavior
    # is unchanged. system_settings.value is JSON — provider ids are
    # stored as JSON numbers or strings; #>> '{}' extracts the scalar.
    op.execute("""
        UPDATE payment_providers
           SET listed_for_inr = TRUE
         WHERE id = (
            SELECT NULLIF(value #>> '{}', '')::int
              FROM system_settings
             WHERE key = 'payment.active_provider_id'
         )
    """)
    op.execute("""
        UPDATE payment_providers
           SET listed_for_intl = TRUE, intl_rank = 10
         WHERE id = (
            SELECT NULLIF(value #>> '{}', '')::int
              FROM system_settings
             WHERE key = 'payment.non_inr_provider_id'
         )
    """)


def downgrade() -> None:
    op.drop_column("payments", "provider_config_id")
    op.drop_column("payment_providers", "intl_rank")
    op.drop_column("payment_providers", "listed_for_intl")
    op.drop_column("payment_providers", "listed_for_inr")
