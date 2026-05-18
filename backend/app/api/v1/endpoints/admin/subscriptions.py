"""Admin manual plan grant / revoke / extend.

Unblocks the recurring support scenario where a payment was debited
at the gateway (typically PayPal PENDING that never released, or a
webhook we missed) but our system shows "no active subscription" —
the user is locked out despite having paid. The admin opens the
user's profile, picks a plan, and grants access manually.

All three mutating endpoints write an audit_logs row keyed by an
``admin.subscription.*`` action prefix so the operator dashboard can
later distinguish manually-granted access from paid access (and
reviewers can audit who granted what, when, and why).

RBAC: admin OR super_admin can grant/revoke/extend (operational
flexibility — any support operator on the rotation can resolve a
stuck-payment case). The grant_reason / revoke_reason fields are
required and captured in both the subscription row + the audit log,
so accountability survives even if an admin role is later revoked.

Endpoints:
  GET   /admin/users/{user_id}/subscriptions          — list all subs (current + historical)
  POST  /admin/users/{user_id}/subscriptions          — grant a new sub
  POST  /admin/subscriptions/{id}/extend              — bump expires_at
  POST  /admin/subscriptions/{id}/revoke              — mark inactive
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.deps import get_admin_user, get_db
from app.core.exceptions import AppError, NotFoundError, ValidationError
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User


router = APIRouter()


# ---------------------------------------------------------------- schemas

class SubscriptionAdminOut(BaseModel):
    """Admin-facing subscription row. Surfaces both organic 'paid' rows
    and admin-granted rows uniformly; the ``source`` + ``granted_by``
    fields let the UI badge them differently."""
    id: int
    user_id: int
    plan: str
    plan_id: int | None
    status: str
    expires_at: datetime | None
    current_period_start: datetime | None
    current_period_end:   datetime | None
    # Manual-grant + revoke fields (migration 0022)
    source: str                        # NULL coerced to 'paid' on read
    granted_by_user_id: int | None
    granted_by_email:   str | None     # joined for the UI; None for organic paid
    grant_reason: str | None
    revoked_at: datetime | None
    revoked_by_user_id: int | None
    revoked_by_email:   str | None
    revoke_reason: str | None
    # Derived: matches the paywall's view of this row right now
    is_active_now: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionGrantIn(BaseModel):
    """Admin manually grants a paid plan to a user. ``period_days`` is
    explicit (not derived from plan.duration_days) so the operator
    can comp a fixed-duration extension that doesn't match any plan's
    standard term (e.g. "give them 30 days while we sort the refund")."""
    plan_id: int = Field(..., description="Plan to grant; must exist.")
    period_days: int = Field(
        ..., ge=1, le=3650,
        description="Number of days from now until expires_at. Cap at "
                    "3650 (10 years) to prevent typo accidents.")
    reason: str = Field(
        ..., min_length=3, max_length=500,
        description="Operator's free-text reason. Captured in both the "
                    "subscription row + the audit log. Required.")
    source: Literal["manual_admin_grant", "comp", "refund_reversed"] = (
        Field("manual_admin_grant",
              description="Provenance tag. 'manual_admin_grant' = "
                          "compensating for a gateway issue (stuck "
                          "payment). 'comp' = free comp (no payment "
                          "ever happened). 'refund_reversed' = a "
                          "refund was reversed and access restored."))


class SubscriptionExtendIn(BaseModel):
    """Bump an existing subscription's ``expires_at`` by ``days``.
    Use case: a paid user's gateway charge got delayed by a few days,
    so they effectively lost that time — admin adds it back."""
    days: int = Field(..., ge=1, le=365,
                       description="Days to add to expires_at.")
    reason: str = Field(..., min_length=3, max_length=500)


class SubscriptionRevokeIn(BaseModel):
    """Mark a subscription as revoked (typically after a refund).
    Sets ``revoked_at`` so the paywall ignores the row regardless
    of ``expires_at``."""
    reason: str = Field(..., min_length=3, max_length=500)


# ---------------------------------------------------------------- serialization

def _to_admin_out(sub: Subscription,
                  email_by_user_id: dict[int, str]) -> SubscriptionAdminOut:
    """Build the admin view of a single subscription row, joining
    granted_by / revoked_by user emails from a pre-fetched lookup
    table (avoids N+1 over the list endpoint)."""
    now = datetime.now(timezone.utc)
    is_active_now = (
        sub.status == "active"
        and (sub.expires_at is None or sub.expires_at > now)
        and sub.revoked_at is None
    )
    return SubscriptionAdminOut(
        id=sub.id, user_id=sub.user_id,
        plan=sub.plan or "(unnamed)",
        plan_id=sub.plan_id,
        status=sub.status,
        expires_at=sub.expires_at,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        source=sub.effective_source,    # NULL → 'paid'
        granted_by_user_id=sub.granted_by,
        granted_by_email=email_by_user_id.get(sub.granted_by or 0),
        grant_reason=sub.grant_reason,
        revoked_at=sub.revoked_at,
        revoked_by_user_id=sub.revoked_by,
        revoked_by_email=email_by_user_id.get(sub.revoked_by or 0),
        revoke_reason=sub.revoke_reason,
        is_active_now=is_active_now,
        created_at=sub.created_at,
    )


def _emails_for(db: Session, user_ids: set[int]) -> dict[int, str]:
    """Bulk-fetch user emails for granted_by / revoked_by joins."""
    if not user_ids:
        return {}
    rows = db.query(User.id, User.email).filter(User.id.in_(user_ids)).all()
    return {uid: email for uid, email in rows}


# ---------------------------------------------------------------- endpoints

@router.get("/users/{user_id}/subscriptions",
            response_model=list[SubscriptionAdminOut])
def list_user_subscriptions(user_id: int,
                             db: Session = Depends(get_db),
                             _admin: User = Depends(get_admin_user)):
    """All subscription rows for one user (current + historical, both
    organic and admin-granted). Sorted by most recently created first
    so the active row is at the top of the support operator's view."""
    user = db.get(User, user_id)
    if not user:
        raise NotFoundError()
    subs = (db.query(Subscription)
            .filter(Subscription.user_id == user_id)
            .order_by(desc(Subscription.created_at))
            .all())
    if not subs:
        return []
    # Bulk-fetch the granted_by + revoked_by emails so the UI can
    # show "granted by alice@..." without N+1.
    actor_ids: set[int] = set()
    for s in subs:
        if s.granted_by is not None:
            actor_ids.add(s.granted_by)
        if s.revoked_by is not None:
            actor_ids.add(s.revoked_by)
    emails = _emails_for(db, actor_ids)
    return [_to_admin_out(s, emails) for s in subs]


@router.post("/users/{user_id}/subscriptions",
             response_model=SubscriptionAdminOut, status_code=201)
def grant_subscription(user_id: int, payload: SubscriptionGrantIn,
                        db: Session = Depends(get_db),
                        admin: User = Depends(get_admin_user)):
    """Manually grant a paid plan to a user (operator backstop for
    stuck-payment cases). Creates a new Subscription row tagged with
    the admin's identity + reason; audit_logs row written in lockstep."""
    user = db.get(User, user_id)
    if not user:
        raise NotFoundError()
    plan = db.get(Plan, payload.plan_id)
    if not plan:
        raise ValidationError("plan_id does not exist")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=payload.period_days)

    sub = Subscription(
        user_id=user_id,
        plan=plan.slug or plan.name or "manual",
        plan_id=plan.id,
        status="active",
        current_period_start=now,
        current_period_end=expires_at,
        expires_at=expires_at,
        source=payload.source,
        granted_by=admin.id,
        grant_reason=payload.reason,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    audit_log(db, admin.id, "admin.subscription.grant", {
        "target_user_id": user_id,
        "target_user_email": user.email,
        "subscription_id": sub.id,
        "plan_id": plan.id,
        "plan_slug": plan.slug,
        "period_days": payload.period_days,
        "expires_at": expires_at.isoformat(),
        "source": payload.source,
        "reason": payload.reason,
    })

    emails = _emails_for(db, {admin.id})
    return _to_admin_out(sub, emails)


@router.post("/subscriptions/{subscription_id}/extend",
             response_model=SubscriptionAdminOut)
def extend_subscription(subscription_id: int, payload: SubscriptionExtendIn,
                         db: Session = Depends(get_db),
                         admin: User = Depends(get_admin_user)):
    """Bump expires_at by ``days``. Refuses if the sub is already
    revoked (use grant for a fresh row instead) or if the resulting
    expires_at exceeds 10 years (typo guardrail)."""
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise NotFoundError()
    if sub.revoked_at is not None:
        raise ValidationError(
            "Cannot extend a revoked subscription. Grant a new one instead.")

    now = datetime.now(timezone.utc)
    # Anchor on the later of (current expires_at, now) so extending a
    # lapsed sub from today's date works; extending a future-dated sub
    # adds days to the future expiry. Matches payment_lifecycle.py.
    anchor = sub.expires_at if (sub.expires_at and sub.expires_at > now) else now
    new_expiry = anchor + timedelta(days=payload.days)
    if (new_expiry - now).days > 3650:
        raise ValidationError(
            "Resulting expires_at exceeds 10 years; refusing as a typo guard.")

    old_expiry = sub.expires_at
    sub.expires_at = new_expiry
    sub.current_period_end = new_expiry
    db.commit()
    db.refresh(sub)

    audit_log(db, admin.id, "admin.subscription.extend", {
        "subscription_id": sub.id,
        "target_user_id": sub.user_id,
        "days_added": payload.days,
        "old_expires_at": old_expiry.isoformat() if old_expiry else None,
        "new_expires_at": new_expiry.isoformat(),
        "reason": payload.reason,
    })

    actor_ids = {admin.id}
    if sub.granted_by is not None:
        actor_ids.add(sub.granted_by)
    emails = _emails_for(db, actor_ids)
    return _to_admin_out(sub, emails)


@router.post("/subscriptions/{subscription_id}/revoke",
             response_model=SubscriptionAdminOut)
def revoke_subscription(subscription_id: int, payload: SubscriptionRevokeIn,
                         db: Session = Depends(get_db),
                         admin: User = Depends(get_admin_user)):
    """Mark a subscription as revoked. Paywall ignores it from this
    point on regardless of expires_at. Idempotent — re-revoking is a
    no-op (preserves the original revoke audit trail)."""
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise NotFoundError()
    if sub.revoked_at is not None:
        # Already revoked — idempotent return so the UI can safely
        # re-submit without erroring (handy for double-click guards).
        actor_ids = {admin.id}
        if sub.revoked_by is not None:
            actor_ids.add(sub.revoked_by)
        return _to_admin_out(sub, _emails_for(db, actor_ids))

    sub.revoked_at = datetime.now(timezone.utc)
    sub.revoked_by = admin.id
    sub.revoke_reason = payload.reason
    db.commit()
    db.refresh(sub)

    audit_log(db, admin.id, "admin.subscription.revoke", {
        "subscription_id": sub.id,
        "target_user_id": sub.user_id,
        "previous_expires_at": (sub.expires_at.isoformat()
                                if sub.expires_at else None),
        "reason": payload.reason,
    })

    actor_ids = {admin.id}
    if sub.granted_by is not None:
        actor_ids.add(sub.granted_by)
    emails = _emails_for(db, actor_ids)
    return _to_admin_out(sub, emails)
