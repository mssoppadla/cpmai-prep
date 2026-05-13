from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_super_admin_user
from app.core.exceptions import AppError, NotFoundError
from app.core.audit import audit_log
from app.core.security import hash_password
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from app.schemas.auth import UserAdminOut

router = APIRouter()


def _to_admin_out(u: User, sub: Subscription | None) -> UserAdminOut:
    """Build the admin-facing user payload, including login-method and
    subscription summary so the admin UI can show everything in one row.

    The GeoIP enrichment fields (country, city, last_login_*) are
    populated by app.api.v1.endpoints.auth at signup + login time —
    we just surface them here. Nullable for users that pre-date the
    feature and for private-IP / lookup-miss cases.
    """
    return UserAdminOut(
        id=u.id, email=u.email, name=u.name, role=u.role,
        created_at=u.created_at,
        is_active=u.is_active,
        failed_login_count=u.failed_login_count,
        locked_until=u.locked_until,
        last_login_at=u.last_login_at,
        deleted_at=u.deleted_at,
        country=u.country,
        city=u.city,
        last_login_ip=u.last_login_ip,
        last_login_country=u.last_login_country,
        has_google=bool(u.google_id),
        has_password=bool(u.password_hash),
        has_active_subscription=bool(sub),
        subscription_plan=sub.plan if sub else None,
        daily_chat_limit_override=u.daily_chat_limit_override,
    )


@router.get("", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_db),
               q: str | None = None,
               role: UserRole | None = None,
               method: str | None = Query(None, pattern="^(google|password|both)$"),
               include_deleted: bool = Query(
                   False,
                   description="If true, include soft-deleted users in the "
                               "list. Default false — admins rarely want to "
                               "see tombstones unless they're investigating "
                               "an audit/abuse case.",
               ),
               limit: int = Query(50, le=200),
               offset: int = 0):
    query = db.query(User)
    if not include_deleted:
        # Default: hide soft-deleted users. They stay searchable when
        # the operator explicitly passes include_deleted=true (the
        # admin UI surfaces this as a "Show deleted" toggle).
        query = query.filter(User.deleted_at.is_(None))
    if q:
        query = query.filter(
            (User.email.ilike(f"%{q}%")) | (User.name.ilike(f"%{q}%"))
        )
    if role:
        query = query.filter(User.role == role)
    if method == "google":
        query = query.filter(User.google_id.isnot(None))
    elif method == "password":
        query = query.filter(User.password_hash.isnot(None))
    elif method == "both":
        query = query.filter(
            User.google_id.isnot(None), User.password_hash.isnot(None)
        )

    users = (query.order_by(User.id.desc()).offset(offset).limit(limit).all())
    if not users:
        return []
    # Single round-trip for active subscriptions instead of N+1.
    subs = {s.user_id: s for s in db.query(Subscription)
            .filter(Subscription.user_id.in_([u.id for u in users]),
                    Subscription.status == "active").all()}
    return [_to_admin_out(u, subs.get(u.id)) for u in users]


@router.get("/{user_id}", response_model=UserAdminOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub)


@router.patch("/{user_id}/role", response_model=UserAdminOut)
def change_role(user_id: int, role: UserRole,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    old = u.role
    u.role = role
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.role_changed",
              {"target_user_id": user_id, "from": old.value, "to": role.value})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub)


class _PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)


@router.patch("/{user_id}/password", response_model=UserAdminOut)
def reset_password(user_id: int, payload: _PasswordResetIn,
                   db: Session = Depends(get_db),
                   admin: User = Depends(get_super_admin_user)):
    """Super-admin force-resets a user's password.

    Operational use case: a user lost their bootstrap password, or admin
    needs to rotate the super-admin's own credential. The new value is
    accepted from the operator (not generated server-side) so they can
    type it directly into a password manager — and the response does NOT
    echo it back, so it isn't recorded in browser DevTools history.

    Audit row is written with the target user_id but NOT the password.
    """
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    u.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.password_reset_by_admin",
              {"target_user_id": user_id, "target_email": u.email})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub)


class _ChatLimitOverrideIn(BaseModel):
    """Setting `null` clears the override; a non-negative int sets one."""
    daily_chat_limit_override: int | None = Field(default=None, ge=0, le=100000)


@router.patch("/{user_id}/chat-limit", response_model=UserAdminOut)
def set_chat_limit_override(user_id: int, payload: _ChatLimitOverrideIn,
                             db: Session = Depends(get_db),
                             admin: User = Depends(get_super_admin_user)):
    """Set or clear a user's per-day chat limit override.

    NULL = use the global `chat.daily_limit.authenticated` setting.
    Any non-negative int overrides it specifically for this user.
    Audit row captures both old and new values so we can reconstruct
    the policy history of any account.
    """
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()
    old = u.daily_chat_limit_override
    u.daily_chat_limit_override = payload.daily_chat_limit_override
    db.commit()
    db.refresh(u)
    audit_log(db, admin.id, "user.chat_limit_override_set",
              {"target_user_id": user_id, "from": old,
               "to": payload.daily_chat_limit_override})
    sub = (db.query(Subscription)
           .filter_by(user_id=u.id, status="active").first())
    return _to_admin_out(u, sub)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(get_super_admin_user)):
    """Soft-delete a user. Super-admin only. Cannot delete self.

    Uses the SAME redaction flow as ``DELETE /users/me`` (GDPR
    self-service deletion). Why soft-delete instead of hard:

    The User row is referenced as a FK by ~10 child tables (audit_logs,
    leads.converted_user_id, subscriptions, payments, journey_events,
    assistant_logs, exam_sessions, etc.) with NO model-level cascades.
    A hard ``db.delete(u) + db.commit()`` would fail with an integrity
    error from any of those — which is exactly the symptom reported
    on 2026-05-13: "This change conflicts with existing data — most
    often a unique field…" (our generic IntegrityError catch-all).

    Adding cascades isn't the answer either — wiping audit history +
    payment records on user delete would violate Indian tax-law
    retention (7 years on financial rows) and lose forensic data.

    Soft-delete keeps everything intact, redacts the PII, and blocks
    login. The admin can still see the row in /admin/users
    (now with email = ``deleted-{id}@redacted.invalid``), which is
    intentional — junk-account cleanup means "make this account
    unusable", not "scrub all evidence of it ever existing".

    See ``app/services/user_deletion.py`` for the full contract.
    """
    if user_id == admin.id:
        raise AppError("You cannot delete your own account.",
                       status_code=400, code="self_delete_forbidden")
    u = db.get(User, user_id)
    if not u:
        raise NotFoundError()

    # Block deleting the last super-admin to avoid locking the project out.
    if u.role == UserRole.SUPER_ADMIN:
        remaining = (db.query(User)
                     .filter(User.role == UserRole.SUPER_ADMIN,
                             User.id != user_id,
                             User.deleted_at.is_(None))
                     .count())
        if remaining == 0:
            raise AppError(
                "Cannot delete the last super-admin. Promote another user first.",
                status_code=400, code="last_super_admin",
            )

    original_email = u.email   # capture before redaction
    from app.services.user_deletion import soft_delete_user
    applied = soft_delete_user(db, u)

    audit_log(db, admin.id, "user.deleted",
              {"target_user_id": user_id,
               "email": original_email,
               "was_already_deleted": not applied,
               "mode": "soft_delete"})
