"""v6.1: content_pages table (Phase 1 CMS foundation).

Second Phase 1 migration. Creates the ``content_pages`` table — a generic
admin-editable page surface for things like Study Guide, About, Privacy,
Terms, and any other long-form content the operator wants to publish
without a redeploy. The block contents live in a single JSONB column
(per contract Q2) consumed by a BlockNote-based editor (PR #5).

Per contract:

  - I-1: every new table has tenant_id (NOT NULL, default=1, FK with cascade)
  - I-3: queries filter by tenant_id (enforced in app/api layer)
  - I-4: callers resolve tenant via ``get_current_tenant_id()`` (no hardcoding)
  - M-1, M-2, M-3: additive only, downgrade NotImplementedError, single transaction
  - Q2: blocks stored as JSONB (Postgres) / JSON (SQLite for tests)
  - Q3: nav_visibility = always | authenticated | subscribed | hidden

Soft delete:
  Per operator decision (logged in PR description), DELETE through the
  admin API does NOT remove the row. Instead it flips ``is_deleted=true``
  and stamps ``deleted_at`` + ``deleted_by``. List/get/update queries
  filter out deleted rows. This gives us a recovery path before we add
  a "trash" UI or a hard-delete path in a later PR.

Backward compatibility:
  This migration is purely additive. No existing table is touched, no
  existing route changes, no existing user data is affected. Rollback
  before traffic == ``DROP TABLE content_pages;``.

NB on revision ID length: keep it ≤32 chars (Postgres ``alembic_version
.version_num`` is VARCHAR(32)). ``0024_content_pages`` = 19 chars ✓.
Lesson from migration 0023.

Revision ID: 0024_content_pages
Revises: 0023_tenants_foundation
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_content_pages"
down_revision = "0023_tenants_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_pages",
        sa.Column("id", sa.Integer, primary_key=True),
        # Multi-tenancy (contract I-1). Default=1 keeps Phase 1 inserts
        # working without plumbing tenant_id through every code path.
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        # URL-safe slug, unique WITHIN a tenant (not globally — two
        # tenants can both have "about" or "privacy"). Public renderer
        # (PR #6) will route /study-guide and /pages/{slug} to these.
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        # The actual page content. A BlockNote document is a JSON array
        # of block objects. Empty list is a valid "just created, not
        # yet edited" state. We store as JSON (not JSONB) so SQLite
        # tests work; on Postgres SQLAlchemy maps to JSON which is
        # automatically jsonb when the dialect supports it — actually
        # the safest cross-dialect choice is sa.JSON (postgres uses
        # JSON, not JSONB, but admin pages aren't queried by content
        # internals so JSON is fine and SQLite-compatible).
        sa.Column("blocks", sa.JSON, nullable=False, server_default="[]"),
        # Nav visibility (contract Q3). Stored as string so we can add
        # values later without an enum migration. Validated at the
        # schema layer.
        #   always         — visible in nav for all visitors
        #   authenticated  — visible only to signed-in users
        #   subscribed     — visible only to paid subscribers
        #   hidden         — exists but not in nav (direct-URL only)
        sa.Column("nav_visibility", sa.String(16),
                  nullable=False, server_default="always"),
        # Optional override for the nav-link text. NULL = fall back to title.
        sa.Column("nav_label", sa.String(64), nullable=True),
        # Sort key for the nav. Lower = earlier. Ties broken by title.
        sa.Column("nav_order", sa.Integer, nullable=False,
                  server_default="100"),
        # is_published controls whether the page is visible on the
        # public site at all. Drafts (is_published=false) are admin-
        # visible only. This is separate from nav_visibility (which
        # decides WHO sees it in nav once published).
        sa.Column("is_published", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        # Soft delete fields. NULL on live rows; populated when admin
        # clicks Delete. is_deleted is the queryable filter index.
        sa.Column("is_deleted", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        # Author tracking. NULL is allowed because a user can be
        # soft-deleted (existing pattern) — we don't want their pages
        # to FK-cascade away.
        sa.Column("created_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        # Slug must be unique WITHIN a tenant. The (tenant_id, slug)
        # pair is the natural key for public URL resolution.
        sa.UniqueConstraint("tenant_id", "slug",
                            name="uq_content_pages_tenant_slug"),
    )
    # Hot read path: "active, published pages for tenant X in nav order".
    # Note we don't include is_deleted in the partial index condition
    # because SQLite (tests) doesn't support partial indexes — we'll
    # filter is_deleted in the WHERE clause and rely on this index for
    # the (tenant_id, is_published, nav_order) prefix lookup.
    op.create_index(
        "ix_content_pages_tenant_pub_nav",
        "content_pages",
        ["tenant_id", "is_published", "nav_order"],
    )
    # Admin listing path: "all my tenant's pages ordered by updated".
    op.create_index(
        "ix_content_pages_tenant_updated",
        "content_pages",
        ["tenant_id", "updated_at"],
    )


def downgrade() -> None:
    # Per contract M-2: downgrades are forward-only. Dropping this table
    # would destroy any pages an operator created — never automate that.
    # If you truly want to back out CMS, write a forward migration that
    # exports pages first.
    raise NotImplementedError(
        "0024_content_pages: downgrade is intentionally unimplemented per "
        "the additive-only migration policy. Dropping content_pages would "
        "destroy author work. To reverse course on CMS, write a forward "
        "migration that exports pages to a JSON archive first, then drops "
        "the table — and review the data-preservation contract before "
        "running it."
    )
