"""v5.11: Generalize Payment provider columns for PayPal-alongside-Razorpay.

When the schema was first laid down, Razorpay was the only payment gateway,
so the columns are razorpay-specific. PayPal is being added as a parallel
non-INR provider (INR stays on Razorpay, unchanged). To avoid two-way
column naming (``razorpay_order_id`` + ``paypal_order_id`` + ...), this
migration renames the columns to provider-agnostic names and adds a
``provider_name`` discriminator. Existing Razorpay rows are backfilled
with ``provider_name='razorpay'`` via the column default.

Four operations, all metadata-only on PostgreSQL 11+ (no row rewrites):

  1. ``payments.razorpay_order_id`` → ``payments.provider_order_id``
     RENAME COLUMN. The UNIQUE constraint follows automatically — Postgres
     constraints are bound to columns by oid, not by name, so the
     uniqueness check keeps working under the new name. We ALSO rename
     the constraint itself (``payments_razorpay_order_id_key`` →
     ``payments_provider_order_id_key``) for hygiene; DB-introspection
     tools used by ops will then label it correctly.

  2. ``payments.razorpay_payment_id`` → ``payments.provider_payment_id``
     Plain RENAME COLUMN — no constraint follows because this column has
     no UNIQUE / FK on it. Holds capture_id for PayPal, payment_id for
     Razorpay; the discriminator is provider_name.

  3. ``payments.provider_name VARCHAR(32) NOT NULL DEFAULT 'razorpay'``
     New column. Existing rows backfill to 'razorpay' (the only provider
     they could possibly have come from). The DEFAULT stays on the column
     after the migration so new INR Payment rows don't need to explicitly
     pass it — the orders endpoint will pass it explicitly for clarity,
     but the default is the safety net.

  4. Index on ``provider_name`` — admin reports filter by provider for
     reconciliation. Skinny B-tree, ~2KB for 100K rows; cheap.

Deploy order safety
-------------------
The /payments endpoints read these columns by their NEW names after the
companion code change lands. Migrations run BEFORE the new image is up
(see scripts/vps/deploy.sh). So during the deploy window:

  * Old containers stopped → no readers of razorpay_order_id
  * Migration runs → columns rename atomically
  * New containers start with the new model → read provider_order_id

No race window. If the deploy strategy ever changes to rolling restart,
this migration would need to be split into two stages (add new + dual-
write → swap → drop old) — flagging here because that's the standard
pattern for online schema changes.

Why one migration, not three
----------------------------
All four operations are bound to the same feature shipping date. Splitting
would leave the table in a half-renamed state for hours (between dev,
review, staging, prod migrations) and confuse anyone reading the schema
mid-rollout. The whole change is < 5ms of ALTER work on a 6-figure-row
table — Postgres is happy to do it in one transaction.

Revision ID: 0020_payments_generic_provider
Revises: 0019_geoip_and_secret_flag
"""
from alembic import op


revision = "0020_payments_generic_provider"
down_revision = "0019_geoip_and_secret_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. razorpay_order_id → provider_order_id, plus rename the
    #    auto-generated UNIQUE constraint for naming hygiene.
    op.execute("""
        ALTER TABLE payments
        RENAME COLUMN razorpay_order_id TO provider_order_id
    """)
    # The constraint name is the default Postgres auto-name; if a previous
    # migration manually renamed it, the IF EXISTS keeps this idempotent.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'payments_razorpay_order_id_key'
            ) THEN
                ALTER TABLE payments
                RENAME CONSTRAINT payments_razorpay_order_id_key
                TO payments_provider_order_id_key;
            END IF;
        END
        $$
    """)

    # 2. razorpay_payment_id → provider_payment_id. Nullable, no
    #    constraints, simple rename.
    op.execute("""
        ALTER TABLE payments
        RENAME COLUMN razorpay_payment_id TO provider_payment_id
    """)

    # 3. New provider_name discriminator. Existing rows are all Razorpay
    #    (the only provider that's ever written here), so the DEFAULT
    #    backfills correctly. Postgres 11+ stores the DEFAULT as
    #    pg_attribute.atthasdef metadata for existing rows — no rewrite.
    op.execute("""
        ALTER TABLE payments
        ADD COLUMN IF NOT EXISTS provider_name VARCHAR(32) NOT NULL
            DEFAULT 'razorpay'
    """)

    # 4. Index for admin reporting & reconciliation queries. Skinny
    #    B-tree, no functional impact, helps "show me all PayPal
    #    payments this month" run quickly.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payments_provider_name
        ON payments (provider_name)
    """)


def downgrade() -> None:
    # Forward-only. Going back would break the multi-provider routing
    # code that depends on provider_name to know whether to verify with
    # Razorpay's HMAC or PayPal's certificate API. Roll back via a new
    # forward migration that explicitly addresses why.
    raise NotImplementedError(
        "0020 is forward-only. Roll back via a new migration that "
        "explicitly handles existing PayPal-provider rows."
    )
