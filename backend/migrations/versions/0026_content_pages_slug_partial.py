"""v6.3: content_pages slug uniqueness becomes partial (excludes soft-deleted rows).

Operator request: after an admin soft-deletes a page named ``study-guide``,
they should be able to create a NEW page with the same slug. Previously
the unique constraint covered ALL rows (including soft-deleted ones),
forcing the admin to either rename the old page first or hard-delete
via psql.

This migration:

  1. Drops the existing ``uq_content_pages_tenant_slug`` constraint
     (which covered every row).
  2. Adds a partial unique index ``uq_content_pages_tenant_slug_live``
     that covers only non-deleted rows. Soft-deleted rows can share a
     slug with each other and with live rows.

The application's ``_slug_taken()`` helper is updated in the same PR
to filter ``is_deleted=False`` so the 409 response matches the DB
behavior.

Soft-deleted rows still retain their slug for the audit trail / future
"trash and restore" admin view — we just stop letting them block live
slug allocation.

Per contract:
  - M-1: additive (new index) + reversible drop of existing constraint
  - M-2: downgrade raises NotImplementedError (recreating the broader
    constraint could fail if duplicate slugs now exist among
    soft-deleted rows)
  - M-3: single transaction

Revision ID: 0026_cp_slug_partial (24 chars, under the 32-char Postgres limit).

Revision ID: 0026_cp_slug_partial
Revises: 0025_cp_landing
"""
from alembic import op


revision = "0026_cp_slug_partial"
down_revision = "0025_cp_landing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Drop the old "uniqueness applies to every row" constraint. The
    #    constraint name was assigned by migration 0024.
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE content_pages DROP CONSTRAINT "
            "IF EXISTS uq_content_pages_tenant_slug"
        )
    else:
        # SQLite represents UNIQUE constraints as auto-named indices
        # rather than first-class constraints. Drop by index name.
        op.execute(
            "DROP INDEX IF EXISTS uq_content_pages_tenant_slug"
        )

    # 2. Create the new partial unique index — only live rows count.
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE UNIQUE INDEX uq_content_pages_tenant_slug_live "
            "ON content_pages (tenant_id, slug) "
            "WHERE is_deleted = FALSE"
        )
    else:
        # SQLite uses 1/0 for boolean literals in partial indices.
        op.execute(
            "CREATE UNIQUE INDEX uq_content_pages_tenant_slug_live "
            "ON content_pages (tenant_id, slug) "
            "WHERE is_deleted = 0"
        )


def downgrade() -> None:
    # Per contract M-2: data-preservation. Reverting could fail if
    # admins have created new pages reusing slugs of soft-deleted rows
    # — the broader unique constraint would reject the snapshot. To
    # revert, write a forward migration that renames duplicate soft-
    # deleted slugs first.
    raise NotImplementedError(
        "0026_cp_slug_partial: downgrade is intentionally unimplemented. "
        "Recreating the original full unique constraint could fail if "
        "live + soft-deleted rows share slugs (which the new index "
        "explicitly permits). To revert, write a forward migration that "
        "first renames duplicate slugs on soft-deleted rows, then "
        "recreates the broader constraint."
    )
