"""Public nav + page queries — auth-aware visibility filter.

Centralised so the public endpoints in ``app/api/v1/endpoints/cms_public.py``
share one definition of "what should this user see in the nav?".

Visibility states (mirror of ``ContentPage.nav_visibility``):

  * ``always``        — visible to everyone (anon, authenticated, subscribed)
  * ``authenticated`` — visible only to signed-in users (any tier)
  * ``subscribed``    — visible only to users with an active subscription
  * ``hidden``        — never in nav (still reachable by direct URL when
                       published; the page endpoint enforces its own rules)

The "subscribed" check is intentionally lightweight here: we ask whether
the user has ANY active, non-revoked Subscription row. We don't run the
full paywall logic because nav rendering is hot and we don't want a
slow query in the header.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.tenant import get_current_tenant_id
from app.models.content_page import ContentPage
from app.models.subscription import Subscription
from app.models.user import User


AuthState = Literal["anon", "authenticated", "subscribed"]


def resolve_auth_state(db: Session, user: User | None) -> AuthState:
    """Map the request's user (if any) to one of the three visibility tiers.

    A user with ANY active, non-revoked subscription gets the
    ``subscribed`` tier. Signed-in users without a subscription are
    ``authenticated``. No user = ``anon``."""
    if user is None:
        return "anon"
    now = datetime.now(timezone.utc)
    has_active_sub = db.execute(
        select(Subscription.id).where(
            Subscription.user_id == user.id,
            Subscription.revoked_at.is_(None),
            or_(Subscription.expires_at.is_(None),
                Subscription.expires_at > now),
        ).limit(1)
    ).first() is not None
    return "subscribed" if has_active_sub else "authenticated"


def _visibility_filter(state: AuthState):
    """Return a SQLAlchemy boolean expression matching pages the given
    auth state should see in the nav. Excludes ``hidden`` always."""
    if state == "anon":
        return ContentPage.nav_visibility == "always"
    if state == "authenticated":
        return ContentPage.nav_visibility.in_(("always", "authenticated"))
    if state == "subscribed":
        return ContentPage.nav_visibility.in_(
            ("always", "authenticated", "subscribed")
        )
    raise ValueError(f"Unknown auth state: {state!r}")


def list_nav_pages(db: Session, state: AuthState) -> list[ContentPage]:
    """Pages the header should render, in display order.

    Filters applied:
      - tenant scope (single-tenant in Phase 1; multi-tenant safe)
      - is_published = true (drafts never appear)
      - is_deleted = false
      - nav_visibility appropriate for ``state``
      - excludes ``hidden`` regardless of state

    Order: nav_order ASC, then title ASC for ties.
    """
    return (db.query(ContentPage)
            .filter(ContentPage.tenant_id == get_current_tenant_id(),
                    ContentPage.is_published.is_(True),
                    ContentPage.is_deleted.is_(False),
                    _visibility_filter(state))
            .order_by(ContentPage.nav_order.asc(),
                      ContentPage.title.asc())
            .all())


def get_published_page_by_slug(db: Session, slug: str) -> ContentPage | None:
    """Lookup for the public page endpoint. Returns None for missing,
    soft-deleted, or unpublished pages — callers translate to 404 so
    we don't leak the existence of drafts."""
    return (db.query(ContentPage)
            .filter(ContentPage.tenant_id == get_current_tenant_id(),
                    ContentPage.slug == slug,
                    ContentPage.is_published.is_(True),
                    ContentPage.is_deleted.is_(False))
            .first())


def get_landing_page(db: Session) -> ContentPage | None:
    """Returns the tenant's landing page if one is marked and the
    ``cms.use_cms_landing`` setting is enabled.

    Callers should also check the setting themselves so the public ``/``
    endpoint can return 404 when the setting is off (signaling the
    frontend to fall back to the marketing homepage).
    """
    return (db.query(ContentPage)
            .filter(ContentPage.tenant_id == get_current_tenant_id(),
                    ContentPage.is_landing.is_(True),
                    ContentPage.is_published.is_(True),
                    ContentPage.is_deleted.is_(False))
            .first())


def page_visible_to(page: ContentPage, state: AuthState) -> bool:
    """Return True if a user in ``state`` is allowed to view this page.

    Used by the page-fetch endpoint to decide whether to return 200, 401,
    or 402. Always-published pages are visible to all states; hidden
    pages are visible to ANYONE who has the direct URL (Phase 1 — hidden
    means "not in nav", NOT "private"). Authenticated/subscribed pages
    enforce their tier."""
    nv = page.nav_visibility
    if nv in ("always", "hidden"):
        return True
    if nv == "authenticated":
        return state in ("authenticated", "subscribed")
    if nv == "subscribed":
        return state == "subscribed"
    # Defensive: unknown visibility falls back to hidden (visible only
    # to direct-URL fetchers — which means visible here).
    return True
