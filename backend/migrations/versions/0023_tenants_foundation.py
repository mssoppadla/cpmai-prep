"""v6.0: tenants table + audit_logs.tenant_id (Phase 1 multi-tenancy foundation).

First Phase 1 migration. Creates the ``tenants`` table that all future
tenant-scoped tables will FK to, and adds a nullable ``tenant_id``
column to ``audit_logs`` so Phase 1 audit events can be tenant-scoped.

CPMAI Prep is pre-seeded as tenant id=1. This row is permanent — it
cannot be deleted (enforced at the application layer; we don't add a
DB-level constraint because Postgres can't easily express "this specific
row is protected").

Why ``audit_logs`` is the only existing table getting tenant_id in this
migration:

  Other Phase-1-relevant tables (content_pages, courses, sessions,
  campaigns) don't exist yet — they get tenant_id natively in their own
  creation migrations (0024, 0025, 0026, 0027).

  Tables that won't be tenant-scoped in Phase 1 (users, subscriptions,
  exam_sets, etc.) get tenant_id ADDED in Phase 2 if/when SaaS launch
  is approved, NOT now. Per the contract:

      "Existing tables stay untouched in Phase 1. Phase 2 adds tenant_id
       columns with default=1 to user-facing tables."

  audit_logs is the exception because Phase 1 features will write audit
  events that NEED to be tenant-scoped from day 1 (e.g., who edited
  which tenant's Study Guide page).

Per contract:
- I-1: every new table has tenant_id (tenants table itself, of course,
  doesn't FK to itself)
- I-2: tenants table seeded with CPMAI as id=1
- Q1: audit_logs.tenant_id added in this migration, backfilled to 1
- M-1, M-2, M-3: additive only, downgrade NotImplementedError, single
  transaction backfill

NB: Revision ID is kept short (≤32 chars) because Postgres's default
``alembic_version.version_num`` column is VARCHAR(32). A longer ID would
let the migration's DDL execute successfully but then crash when alembic
tries to record the new version in alembic_version — Postgres would
roll back the whole transaction. The descriptive docstring above carries
the full intent; the ID is just the index.

Revision ID: 0023_tenants_foundation
Revises: 0022_subscriptions_admin_grant
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_tenants_foundation"
down_revision = "0022_subscriptions_admin_grant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tenants table ---------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        # Plan = "free" | "starter" | "growth" | "pro" | "enterprise".
        # Phase 1: CPMAI gets "enterprise" → no plan-tier gating applies.
        # Phase 2: real plans + billing.
        sa.Column("plan", sa.String(32), nullable=False, server_default="enterprise"),
        # Status = "active" | "suspended" | "deleted". Phase 1: always "active".
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        # Per-tenant settings stored as JSON for flexibility (per contract
        # H-7 namespacing). Phase 1: empty {}; Phase 2: tenant overrides
        # of global settings, BYOK keys, etc.
        sa.Column("settings_json", sa.JSON, nullable=False, server_default="{}"),
        # Storage quota tracking (per contract S-2). Phase 1: CPMAI =
        # enterprise = unlimited; quota only enforced in Phase 2.
        sa.Column("storage_used_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_quota_bytes", sa.BigInteger, nullable=True),  # NULL = unlimited
        # Encrypted payment-gateway credentials for Flow B (tenant bills
        # their end-users). Phase 1: CPMAI's existing Razorpay/PayPal
        # creds live in payment_providers table (untouched); Phase 2
        # tenants put theirs here. Encrypted via existing Fernet infra
        # (ENCRYPTION_KEY) — never logged.
        sa.Column("payment_gateway_config_encrypted", sa.Text, nullable=True),
        # Feature flags override (per contract F-3). JSON map of
        # feature → enabled bool. Phase 1: empty.
        sa.Column("feature_overrides", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_status", "tenants", ["status"])

    # --- Seed CPMAI as tenant id=1 ---------------------------------------
    # Per contract I-2: this row is permanent. The seeder + admin code
    # must refuse to delete tenant_id=1 (enforced in Phase 2 super-admin
    # endpoints).
    #
    # We INSERT with explicit id=1 so future tenants get id=2, 3, ...
    # Different DBs handle sequence-after-explicit-id differently:
    #   - Postgres: serial sequence may need a manual setval after this
    #     (handled by the seeder on next run, or by deploy script)
    #   - SQLite (tests): rowid mechanism auto-advances correctly
    op.execute(
        "INSERT INTO tenants (id, slug, name, plan, status, "
        "settings_json, storage_used_bytes, feature_overrides) "
        "VALUES (1, 'cpmai', 'CPMAI Prep', 'enterprise', 'active', "
        "'{}', 0, '{}')"
    )

    # --- audit_logs.tenant_id (per Q1) -----------------------------------
    # Nullable on add, then backfill = 1 for all existing rows, then add
    # NOT NULL — but only on Postgres. SQLite doesn't support ALTER
    # COLUMN to add NOT NULL after the fact, so on SQLite we leave it
    # nullable. The application layer treats NULL as tenant_id=1 anyway
    # (per contract MR-4 mitigation), so this is safe.
    op.add_column(
        "audit_logs",
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=True),
    )

    # Backfill existing rows
    op.execute("UPDATE audit_logs SET tenant_id = 1 WHERE tenant_id IS NULL")

    # Add NOT NULL constraint on Postgres only (SQLite for tests is
    # treated as best-effort backward-compat). The runtime behaviour is
    # the same either way: app code coerces NULL → 1 on read.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column("audit_logs", "tenant_id", nullable=False)

    # Index for the hot read pattern "audit logs for tenant X recently"
    op.create_index(
        "ix_audit_logs_tenant_id_created_at",
        "audit_logs", ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    # Data-preservation contract M-2: downgrades are forward-only.
    # To remove tenant scoping after this migration, drop the column
    # AND drop the tenants table — both are destructive operations
    # that should never happen in an automated rollback.
    raise NotImplementedError(
        "0023_tenants_foundation: downgrade is "
        "intentionally unimplemented per the additive-only migration "
        "policy. Removing tenant scoping would delete the tenants "
        "table and cascade-drop tenant_id columns — never automate "
        "this. To reverse course on multi-tenancy, write a forward "
        "migration that adjusts the schema explicitly."
    )
