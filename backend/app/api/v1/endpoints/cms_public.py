"""Public CMS endpoints — what the end-user frontend calls.

Three routes, NO ``/admin`` prefix (mounted at /api/v1/cms/):

  * GET /api/v1/cms/nav          → ordered list of nav links the header should render
  * GET /api/v1/cms/pages/{slug} → one published page by slug
  * GET /api/v1/cms/landing      → the tenant's CMS landing page (or 404)

Auth model: optional bearer token. If present, the user's visibility
tier (anon/authenticated/subscribed) widens what's returned. Anon
users see only ``nav_visibility=always`` pages. Subscribed users see
all three tiers.

Authorisation for the page endpoint:

  - Pages with ``nav_visibility=always`` → 200 to all callers
  - Pages with ``nav_visibility=hidden`` → 200 to all callers who know
    the URL (hidden means "not in nav", NOT "private" — Phase 1 decision)
  - ``nav_visibility=authenticated`` requires a bearer → 401 if anon
  - ``nav_visibility=subscribed`` requires active subscription → 402 if not

The landing endpoint additionally honors the
``cms.use_cms_landing`` setting. When false (default), the endpoint
returns 404 unconditionally so the frontend's ``/`` route falls back
to the marketing homepage. This lets the operator test landing pages
in admin without affecting the live site.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_optional_user
from app.core.exceptions import (
    NotFoundError,
    SubscriptionRequiredError,
    UnauthorizedError,
)
from app.core.settings_store import settings_store
from app.models.user import User
from app.schemas.content_page import (
    ContentPageNavItemOut,
    ContentPagePublicOut,
)
from app.services.cms.nav_query import (
    get_landing_page,
    get_published_page_by_slug,
    list_nav_pages,
    page_visible_to,
    resolve_auth_state,
)

router = APIRouter()


@router.get("/nav", response_model=list[ContentPageNavItemOut])
def cms_nav(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Header nav links — auth-aware. Anon sees ``always``-visible pages
    only; authenticated adds ``authenticated``; subscribed adds
    ``subscribed`` on top.

    Caches well: no per-user state in the response beyond the
    visibility tier. Frontend can re-fetch on login/logout."""
    state = resolve_auth_state(db, user)
    pages = list_nav_pages(db, state)
    return [
        ContentPageNavItemOut(
            slug=p.slug,
            label=p.effective_nav_label,
            order=p.nav_order,
        )
        for p in pages
    ]


@router.get("/pages/{slug}", response_model=ContentPagePublicOut)
def cms_page(
    slug: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Fetch one published page by slug. Authorises by nav_visibility
    so a page that's only meant for paying users can't be scraped by
    its URL.

    Returns 404 — not 403 — when an anon user hits an authenticated
    page, to avoid leaking the existence of paywalled content. The
    *authentication* status is still surfaced via 401 (so the
    frontend knows to prompt sign-in)."""
    page = get_published_page_by_slug(db, slug)
    if not page:
        raise NotFoundError("Page not found")
    state = resolve_auth_state(db, user)
    if not page_visible_to(page, state):
        if state == "anon":
            raise UnauthorizedError("Sign in to view this page")
        raise SubscriptionRequiredError()
    return page


@router.get("/landing", response_model=ContentPagePublicOut)
def cms_landing(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Returns the CMS landing page IF the ``cms.use_cms_landing``
    setting is enabled AND a page is marked as landing. Else 404.

    The frontend's ``/`` route calls this; on 404 it renders the
    existing marketing homepage."""
    if not bool(settings_store.get("cms.use_cms_landing", False)):
        raise NotFoundError("CMS landing is not enabled")
    page = get_landing_page(db)
    if not page:
        raise NotFoundError("No landing page configured")
    # Landing pages are always public — but if the operator set the
    # page to authenticated/subscribed visibility, honour it (might be
    # an intentional sign-up wall).
    state = resolve_auth_state(db, user)
    if not page_visible_to(page, state):
        if state == "anon":
            raise UnauthorizedError("Sign in to view this page")
        raise SubscriptionRequiredError()
    return page
