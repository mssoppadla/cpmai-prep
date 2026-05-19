"""v6.2: content_pages.is_landing + partial unique index (one landing per tenant).

Third Phase 1 CMS migration. Adds the ``is_landing`` boolean so an
admin can mark exactly one content_page per tenant as the site's
landing page. Backed by a partial unique index so the database
enforces "at most one is_landing=true per tenant" — no application-
layer race can create two.

Why a partial index, not a CHECK constraint:

  A CHECK can validate row-local invariants. "Only one landing per
  tenant" is a multi-row invariant, which is what unique indexes
  exist for. The partial index keeps the unique-key narrow (only
  active landings participate) so we don't have to manage a
  composite "NULL means not landing" hack.

The application layer additionally wraps the set-landing operation
in a transaction (unset previous landing → set new landing → commit)
so we never trip the unique constraint mid-flight on Postgres.

Per contract:
  - M-1: additive only (new column with safe default)
  - M-2: downgrade NotImplementedError (data-preservation)
  - M-3: single-transaction; ``server_default=false`` so existing rows
    backfill cleanly without a separate UPDATE step

Revision ID is 24 chars (under the 32-char Postgres limit — lesson
from PR #3).

Revision ID: 0025_cp_landing
Revises: 0024_content_pages
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_cp_landing"
down_revision = "0024_content_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_pages",
        sa.Column("is_landing", sa.Boolean,
                  nullable=False, server_default=sa.false()),
    )

    # Partial unique index: at most one landing per tenant, ignoring
    # soft-deleted rows. SQLite (tests) supports partial indexes since
    # 3.8, so this works in both dialects.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE UNIQUE INDEX uq_content_pages_one_landing_per_tenant "
            "ON content_pages (tenant_id) "
            "WHERE is_landing = TRUE AND is_deleted = FALSE"
        )
    else:
        # SQLite uses 1/0 for boolean literals in indices.
        op.execute(
            "CREATE UNIQUE INDEX uq_content_pages_one_landing_per_tenant "
            "ON content_pages (tenant_id) "
            "WHERE is_landing = 1 AND is_deleted = 0"
        )


def downgrade() -> None:
    # Per contract M-2: downgrades are forward-only. Dropping the
    # ``is_landing`` column would silently strip the landing-page
    # designation from every page. To revert CMS landing logic, write
    # a forward migration that explicitly handles the landing pointer.
    raise NotImplementedError(
        "0025_cp_landing: downgrade is intentionally unimplemented per the "
        "additive-only migration policy. Dropping is_landing would lose the "
        "landing-page selection. To revert, write a forward migration that "
        "first clears the setting + handles the orphaned pointer."
    )
