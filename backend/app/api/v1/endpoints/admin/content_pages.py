"""Admin CRUD for ContentPage — drives the CMS at /admin/content-pages.

Every endpoint here is gated by ``get_admin_user`` at the parent
router level. We additionally:

  - Filter every read by ``get_current_tenant_id()`` (contract I-3).
  - Stamp ``tenant_id`` on every insert via the same helper (contract I-4).
  - Soft-delete via the DELETE endpoint (flip ``is_deleted``, stamp who/when).
  - Audit-log every create / update / delete with the tenant_id, page id,
    and a short summary (slug, title) for trail readability.

Soft delete is the ONLY delete path in Phase 1. There is no hard-delete
endpoint and no automatic purge. A future "Trash" admin view can list
soft-deleted pages, undelete them, or hard-delete after retention. Until
then, soft-deleted rows are invisible to the API but recoverable via DB
console if something goes wrong.

Slug collision is enforced both at the DB level (``UniqueConstraint``
on ``(tenant_id, slug)``) and at the API level (we explicitly check
before insert/update so the client gets a clean 409 instead of a 500
from a constraint violation).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.tenant import get_current_tenant_id
from app.models.content_page import ContentPage
from app.models.user import User
from app.schemas.content_page import (
    ContentPageCreateIn,
    ContentPageOut,
    ContentPageUpdateIn,
)

router = APIRouter()


# ----------------------------------------------------------- helpers

def _scoped_query(db: Session):
    """Base query: tenant-scoped, soft-delete-excluded.

    Every list/get path goes through this so we can't accidentally
    leak rows across tenants or surface deleted rows. Contract I-3.
    """
    return db.query(ContentPage).filter(
        ContentPage.tenant_id == get_current_tenant_id(),
        ContentPage.is_deleted.is_(False),
    )


def _slug_taken(db: Session, slug: str, *, exclude_id: int | None = None) -> bool:
    """Is this slug already used by ANY page in the current tenant?

    Includes soft-deleted pages — the DB unique constraint covers them
    too, and pre-empting the DB error here gives the client a clean 409
    instead of a 500. Restoring or renaming the soft-deleted page is
    the operator's path to reusing a slug.
    """
    q = db.query(ContentPage.id).filter(
        ContentPage.tenant_id == get_current_tenant_id(),
        ContentPage.slug == slug,
    )
    if exclude_id is not None:
        q = q.filter(ContentPage.id != exclude_id)
    return db.query(q.exists()).scalar()


# ----------------------------------------------------------- routes

@router.get("", response_model=list[ContentPageOut])
def list_content_pages(
    db: Session = Depends(get_db),
    include_unpublished: bool = Query(
        True,
        description=(
            "Admin list shows both drafts and published pages by default; "
            "set to false to filter to published only."
        ),
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List content pages for the current tenant.

    Soft-deleted rows are excluded. Drafts (is_published=false) are
    included by default — this is the admin view; the public renderer
    in PR #6 will filter them out.
    """
    q = _scoped_query(db)
    if not include_unpublished:
        q = q.filter(ContentPage.is_published.is_(True))
    return (q.order_by(ContentPage.nav_order, ContentPage.id)
            .offset(offset).limit(limit).all())


@router.get("/{page_id}", response_model=ContentPageOut)
def get_content_page(page_id: int, db: Session = Depends(get_db)):
    page = _scoped_query(db).filter(ContentPage.id == page_id).first()
    if not page:
        raise NotFoundError("Content page not found")
    return page


@router.post("", response_model=ContentPageOut, status_code=201)
def create_content_page(
    payload: ContentPageCreateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Create a new page in the current tenant.

    Slug must be unique within the tenant (live, non-deleted pages).
    Soft-deleted pages with the same slug do NOT block creation — they
    can be hard-deleted by an operator if needed.
    """
    if _slug_taken(db, payload.slug):
        raise ConflictError(
            f"A page with slug '{payload.slug}' already exists."
        )
    page = ContentPage(
        tenant_id=get_current_tenant_id(),
        slug=payload.slug,
        title=payload.title,
        blocks=payload.blocks,
        nav_visibility=payload.nav_visibility,
        nav_label=payload.nav_label,
        nav_order=payload.nav_order,
        is_published=payload.is_published,
        created_by=admin.id,
    )
    db.add(page); db.commit(); db.refresh(page)
    audit_log(
        db, admin.id, "content_page.created",
        {"id": page.id, "slug": page.slug, "title": page.title},
    )
    return page


@router.patch("/{page_id}", response_model=ContentPageOut)
def update_content_page(
    page_id: int,
    payload: ContentPageUpdateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    page = _scoped_query(db).filter(ContentPage.id == page_id).first()
    if not page:
        raise NotFoundError("Content page not found")

    updates = payload.model_dump(exclude_unset=True)

    # If the client is changing the slug, re-check uniqueness within tenant.
    new_slug = updates.get("slug")
    if new_slug is not None and new_slug != page.slug:
        if _slug_taken(db, new_slug, exclude_id=page.id):
            raise ConflictError(
                f"A page with slug '{new_slug}' already exists."
            )

    for key, value in updates.items():
        setattr(page, key, value)
    db.commit(); db.refresh(page)
    audit_log(
        db, admin.id, "content_page.updated",
        {"id": page.id, "slug": page.slug, "changed": sorted(updates.keys())},
    )
    return page


@router.delete("/{page_id}", status_code=204)
def delete_content_page(
    page_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Soft delete: flips ``is_deleted=true`` and stamps who/when.

    The row remains in the database for recovery. A separate
    super-admin / Phase 2 endpoint will offer hard-delete + restore.
    Re-deleting an already-deleted page is a 404 (it's not visible to
    the API any more).
    """
    page = _scoped_query(db).filter(ContentPage.id == page_id).first()
    if not page:
        raise NotFoundError("Content page not found")
    page.is_deleted = True
    page.deleted_at = datetime.now(timezone.utc)
    page.deleted_by = admin.id
    db.commit()
    audit_log(
        db, admin.id, "content_page.deleted",
        {"id": page.id, "slug": page.slug, "soft": True},
    )
    # No response body on 204
