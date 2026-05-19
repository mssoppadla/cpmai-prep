"""ContentPage model — admin-editable long-form pages (CMS Phase 1).

Backs the BlockNote editor at /admin/content-pages (PR #5) and the public
renderer at /study-guide and /pages/{slug} (PR #6). The block content is
a JSON list of BlockNote blocks; the server treats it as opaque JSON in
Phase 1 (no server-side block-shape validation).

Multi-tenancy (per contract):

  - I-1: tenant_id NOT NULL, default=1, FK → tenants.id ON DELETE CASCADE.
  - I-3: every read query MUST filter by tenant_id. Endpoint code uses
    ``get_current_tenant_id()`` from app.core.tenant — never hardcoded.
  - Unique key is (tenant_id, slug). Two tenants can both have an
    "about" page; slugs only need to be unique within a tenant.

Soft delete pattern:

  Admin DELETE flips ``is_deleted=true`` and stamps timestamps. Live
  queries filter ``is_deleted == False``. A future Phase-2 "Trash" view
  can list deleted pages, undelete them, or hard-delete after retention.

Author tracking:

  ``created_by`` / ``deleted_by`` use ON DELETE SET NULL — a soft-deleted
  admin's pages remain readable and editable by other admins. We can
  always show "(removed user)" in the UI when this is None.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


# Allowed values for ContentPage.nav_visibility. Kept as a module
# constant (not a SQL enum) so we can add tiers without an enum
# migration. Validated at the Pydantic schema layer.
NAV_VISIBILITY_CHOICES = ("always", "authenticated", "subscribed", "hidden")


class ContentPage(Base):
    __tablename__ = "content_pages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug",
                         name="uq_content_pages_tenant_slug"),
    )

    id = Column(Integer, primary_key=True)

    # Tenant scope. NEVER trust client input for this — every endpoint
    # uses ``get_current_tenant_id()`` to set it on insert and to filter
    # on read.
    tenant_id = Column(Integer,
                       ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=False, default=1, index=True)

    # URL-safe slug. Validated at the schema layer (alphanum + dash).
    # Unique within a tenant — see UniqueConstraint above.
    slug = Column(String(128), nullable=False)

    # Human-readable page title. Used as the default nav label and
    # <title> tag on the public renderer.
    title = Column(String(256), nullable=False)

    # BlockNote document — a JSON array of block objects. Empty list
    # is a valid "just created, nothing authored yet" state.
    blocks = Column(JSON, nullable=False, default=list)

    # Nav visibility — one of NAV_VISIBILITY_CHOICES. Stored as string
    # for forward compatibility.
    nav_visibility = Column(String(16), nullable=False, default="always")

    # Optional nav label override. NULL means "use title".
    nav_label = Column(String(64), nullable=True)

    # Sort key for the nav. Lower = earlier in the list.
    nav_order = Column(Integer, nullable=False, default=100)

    # Publication state. Drafts are admin-visible only.
    is_published = Column(Boolean, nullable=False, default=False)

    # Soft delete fields. is_deleted is the queryable flag; the
    # timestamp/user are for audit/forensics.
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(Integer,
                        ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True)

    # Author tracking. SET NULL so soft-deleted users don't take their
    # pages with them.
    created_by = Column(Integer,
                        ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True)

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now(),
                        nullable=False)

    def __repr__(self) -> str:
        return (f"<ContentPage id={self.id} tenant={self.tenant_id} "
                f"slug={self.slug!r} pub={self.is_published} "
                f"del={self.is_deleted}>")

    @property
    def effective_nav_label(self) -> str:
        """The string the nav should actually render for this page."""
        return self.nav_label or self.title
