"""v5.0: pricing plans + offer codes.

Adds the pricing layer that powers the public /pricing page and the
paywall on premium exam sets:

  - plans               — sellable bundles (exam_bundle | course_bundle | custom)
                          with base/discount price, perks json, duration.
  - plan_exam_sets      — M2M: which exam sets each plan unlocks.
  - offer_codes         — global N-redemption discount coupons.
  - offer_redemptions   — append-only audit ledger of who used what.

Also extends:
  - subscriptions       — adds plan_id (FK) + expires_at (1-year time-bound).
                          Legacy `plan` string column kept; populated for
                          new rows as a denormalised label.
  - payments            — adds plan_id, base_amount_paise, discount_paise,
                          offer_code, referrer for audit + analytics.

Forward-only, additive. No data backfill needed (no production rows yet
reference these new columns).

Revision ID: 0007_pricing_plans
Revises: 0006_anon_attempts
"""
from alembic import op


revision = "0007_pricing_plans"
down_revision = "0006_anon_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------- plans
    op.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id                   SERIAL PRIMARY KEY,
            name                 VARCHAR(120) UNIQUE NOT NULL,
            slug                 VARCHAR(140) UNIQUE NOT NULL,
            description          TEXT,
            bundle_type          VARCHAR(32) NOT NULL,
            base_price_paise     INTEGER NOT NULL,
            discount_price_paise INTEGER,
            currency             VARCHAR(8) NOT NULL DEFAULT 'INR',
            duration_days        INTEGER NOT NULL DEFAULT 365,
            perks                JSONB DEFAULT '{}'::jsonb,
            is_active            BOOLEAN NOT NULL DEFAULT TRUE,
            display_order        INTEGER NOT NULL DEFAULT 100,
            created_by           INTEGER REFERENCES users(id),
            created_at           TIMESTAMPTZ DEFAULT NOW(),
            updated_at           TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_plans_is_active ON plans(is_active)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_plans_slug ON plans(slug)
    """)

    # ----------------------------------------------- plan_exam_sets (M2M)
    op.execute("""
        CREATE TABLE IF NOT EXISTS plan_exam_sets (
            plan_id     INTEGER NOT NULL REFERENCES plans(id)     ON DELETE CASCADE,
            exam_set_id INTEGER NOT NULL REFERENCES exam_sets(id) ON DELETE CASCADE,
            added_at    TIMESTAMPTZ DEFAULT NOW(),
            added_by    INTEGER REFERENCES users(id),
            PRIMARY KEY (plan_id, exam_set_id),
            CONSTRAINT uq_plan_exam_set UNIQUE (plan_id, exam_set_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_plan_exam_sets_plan ON plan_exam_sets(plan_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_plan_exam_sets_set  ON plan_exam_sets(exam_set_id)
    """)

    # ---------------------------------------------------- offer_codes
    op.execute("""
        CREATE TABLE IF NOT EXISTS offer_codes (
            id                   SERIAL PRIMARY KEY,
            code                 VARCHAR(48) UNIQUE NOT NULL,
            description          VARCHAR(240),
            discount_type        VARCHAR(16) NOT NULL,
            discount_value       INTEGER NOT NULL,
            valid_from           TIMESTAMPTZ,
            valid_until          TIMESTAMPTZ,
            max_redemptions      INTEGER,
            used_count           INTEGER NOT NULL DEFAULT 0,
            applies_to_plan_ids  JSONB,
            is_active            BOOLEAN NOT NULL DEFAULT TRUE,
            created_by           INTEGER REFERENCES users(id),
            created_at           TIMESTAMPTZ DEFAULT NOW(),
            updated_at           TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_offer_codes_is_active ON offer_codes(is_active)
    """)

    # ------------------------------------------------ offer_redemptions
    op.execute("""
        CREATE TABLE IF NOT EXISTS offer_redemptions (
            id              SERIAL PRIMARY KEY,
            offer_code_id   INTEGER NOT NULL REFERENCES offer_codes(id) ON DELETE RESTRICT,
            user_id         INTEGER NOT NULL REFERENCES users(id),
            plan_id         INTEGER NOT NULL REFERENCES plans(id),
            payment_id      INTEGER NOT NULL REFERENCES payments(id),
            discount_paise  INTEGER NOT NULL,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_redemption_per_payment UNIQUE (offer_code_id, payment_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_offer_redemptions_user ON offer_redemptions(user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_offer_redemptions_code ON offer_redemptions(offer_code_id)
    """)

    # ---------------------------------------- subscriptions: plan_id + expires_at
    op.execute("""
        ALTER TABLE subscriptions
        ADD COLUMN IF NOT EXISTS plan_id    INTEGER REFERENCES plans(id),
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_subscriptions_plan_id    ON subscriptions(plan_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_subscriptions_expires_at ON subscriptions(expires_at)
    """)

    # ----------------------------- payments: plan_id, breakdown columns
    op.execute("""
        ALTER TABLE payments
        ADD COLUMN IF NOT EXISTS plan_id            INTEGER REFERENCES plans(id),
        ADD COLUMN IF NOT EXISTS base_amount_paise  INTEGER,
        ADD COLUMN IF NOT EXISTS discount_paise     INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS offer_code         VARCHAR(48),
        ADD COLUMN IF NOT EXISTS referrer           VARCHAR(240)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_payments_plan_id ON payments(plan_id)
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "0007 is forward-only — paid subscriptions and redemption history "
        "must not be discarded."
    )
