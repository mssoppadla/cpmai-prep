from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.deps import get_db, get_super_admin_user
from app.core.exceptions import NotFoundError
from app.core.audit import audit_log
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from app.schemas.auth import UserAdminOut

router = APIRouter()


def _to_admin_out(u: User, sub: Subscription | None) -> UserAdminOut:
    """Build the admin-facing user payload, including login-method and
    subscription summary so the admin UI can show everything in one row."""
    return UserAdminOut(
        id=u.id, email=u.email, name=u.name, role=u.role,
        created_at=u.created_at,
        is_active=u.is_active,
        failed_login_count=u.failed_login_count,
        locked_until=u.locked_until,
        last_login_at=u.last_login_at,
        has_google=bool(u.google_id),
        has_password=bool(u.password_hash),
        has_active_subscription=bool(sub),
        subscription_plan=sub.plan if sub else None,
    )


@router.get("", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_db),
               q: str | None = None,
               role: UserRole | None = None,
               method: str | None = Query(None, pattern="^(google|password|both)$"),
               limit: int = Query(50, le=200),
               offset: int = 0):
    query = db.query(User)
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
